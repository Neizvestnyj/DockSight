from typing import Any

from docksight.application.views.schemas import ComposeStackCard, ContainerStatusCard, DiagnosisResponse, LogAnomalyCard
from docksight.domain.runtime import ContainerSnapshot
from tests.integration.live_e2e.cases import Case
from tests.integration.live_e2e.lab import ComposeLab


def check_answer(events: list[dict[str, Any]], lab: ComposeLab, case: Case) -> DiagnosisResponse:
    """Validate typed HTTP output against exact real fixture identities and scenario facts."""
    assert events and events[0]["type"] == "turn.started"
    assert events[-1]["type"] == "turn.completed", events[-1]
    assert not any(row["type"] == "turn.failed" for row in events)
    ready = [row for row in events if row["type"] == "answer.ready"]
    assert len(ready) == 1
    answer = DiagnosisResponse.model_validate(ready[0]["answer"])
    ids = {row.id for row in lab.containers.values()}
    references = {row.id: row for row in answer.evidence}
    assert references
    assert all(row.host == "e2e" and row.container_id in ids | {None} for row in references.values())
    assert all(set(widget.evidence_ids) <= references.keys() for widget in answer.widgets)
    check_resource_scope(answer, ids, lab.project)
    if case.group:
        _check_group(answer, lab)
    else:
        _check_container(answer, lab, case)
    _check_logs(answer, lab)
    return answer


def check_resource_scope(answer: DiagnosisResponse, ids: set[str], project: str) -> None:
    """Reject any extra card that introduces a host, container, or group outside the real fixture."""
    for card in answer.widgets:
        if isinstance(card, ContainerStatusCard):
            assert card.snapshot.id in ids and card.snapshot.host == "e2e"
        elif isinstance(card, ComposeStackCard):
            assert card.host == "e2e"
            assert all((row.kind, row.name) == ("compose", project) for row in card.stacks)
        else:
            assert card.container_id in ids and card.host == "e2e"


def _check_group(answer: DiagnosisResponse, lab: ComposeLab) -> None:
    """Require both independent failures, not a plausible explanation for only the last inspected container."""
    assert answer.group is not None
    group = answer.group.summary
    assert (group.kind, group.name, group.total, group.running) == ("compose", lab.project, 3, 1)
    assert {row.id for row in group.members} == {row.id for row in lab.containers.values()}
    failed = {lab.containers[name].id for name in ("backend", "grafana")}
    states = {row.id: row.state for row in group.members}
    assert (states[lab.containers["backend"].id], states[lab.containers["grafana"].id]) == ("exited", "exited")
    status = [row.snapshot.id for row in answer.widgets if isinstance(row, ContainerStatusCard)]
    logs = [row.container_id for row in answer.widgets if isinstance(row, LogAnomalyCard)]
    assert failed <= set(status)
    assert failed <= set(logs)
    assert len(status) == len(set(status)), "Duplicate state cards for the same group member"
    assert len(logs) == len(set(logs)), "Duplicate log cards for the same group member"
    assert {row.container_id for row in answer.group.logs} >= failed
    _check_failed_cards(answer, failed)


def _check_failed_cards(answer: DiagnosisResponse, failed: set[str]) -> None:
    """Check actual state values inside each problem card, not just its presence and identity."""
    for card in answer.widgets:
        if isinstance(card, ContainerStatusCard) and card.snapshot.id in failed:
            snapshot = card.snapshot
            assert (snapshot.state, snapshot.exit_code, snapshot.oom_killed, snapshot.restart_count) == (
                "exited",
                1,
                False,
                0,
            )
            assert snapshot.metrics.cpu_percent is None
            assert snapshot.metrics.memory_usage_bytes is None


def _check_container(answer: DiagnosisResponse, lab: ComposeLab, case: Case) -> None:
    """Keep missing runtime values, a genuine OOM, and a non-OOM exit 137 distinguishable."""
    cards = [row for row in answer.widgets if isinstance(row, ContainerStatusCard)]
    assert len(cards) == 1
    snapshot = cards[0].snapshot
    assert snapshot.id == next(iter(lab.containers.values())).id
    if case.name == "crash-loop":
        assert snapshot.restart_count >= 2
        assert snapshot.state in {"running", "restarting", "exited"}
    elif case.name == "truncated-logs":
        assert snapshot.state == "running"
        assert any(row.logs.truncated for row in answer.widgets if isinstance(row, LogAnomalyCard))
    else:
        _check_exited(snapshot, case)
    _check_uncertainty(answer, case)


def _check_exited(snapshot: ContainerSnapshot, case: Case) -> None:
    """Differentiate Docker-confirmed OOM from the same exit code without OOM evidence."""
    assert (snapshot.state, snapshot.exit_code) == ("exited", 137)
    assert snapshot.oom_killed is (case.name == "oom")
    assert snapshot.metrics.memory_usage_bytes is None
    assert snapshot.metrics.cpu_percent is None


def _check_uncertainty(answer: DiagnosisResponse, case: Case) -> None:
    """An unobserved exit reason must remain explicitly unresolved."""
    if case.name == "unknown-exit":
        assert answer.uncertain or (answer.cause and answer.cause.unknowns), "The exit reason is not established"


def _check_logs(answer: DiagnosisResponse, lab: ComposeLab) -> None:
    """Check actual per-container log content and provenance rather than model-authored wording."""
    containers = {row.id: row for row in lab.containers.values()}
    cards = [row for row in answer.widgets if isinstance(row, LogAnomalyCard)]
    assert cards, "The diagnosis omitted supported requested logs"
    for card in cards:
        assert card.host == "e2e" and card.container_id in containers
        _check_log_source(card, answer)
        raw = containers[card.container_id].logs(tail=100).decode("utf-8", errors="replace")
        assert all(entry.message in raw for entry in card.logs.entries), "Log card contains unobserved content"


def _check_log_source(card: LogAnomalyCard, answer: DiagnosisResponse) -> None:
    """Require bounded lines and exact-resource references for each log card."""
    sources = {row.id: row for row in answer.evidence}
    assert 0 < len(card.logs.entries) <= 30
    assert any(sources[ref].kind == "logs" for ref in card.evidence_ids)
    assert all(sources[ref].container_id in {None, card.container_id} for ref in card.evidence_ids)
