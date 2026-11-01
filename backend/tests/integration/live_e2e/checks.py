import re
from typing import Any, Final

from docksight.application.views.schemas import (
    ComposeStackCard,
    ContainerStatusCard,
    DiagnosisResponse,
    GroupSelection,
    LogAnomalyCard,
)
from docksight.domain.runtime import ContainerSnapshot
from tests.integration.live_e2e.cases import Case
from tests.integration.live_e2e.causal_checks import check_causality
from tests.integration.live_e2e.host_checks import check_host
from tests.integration.live_e2e.lab import ComposeLab

# Covers the 800-line finite fixture and continuous probes within 90s setup plus a 240s turn.
_SOURCE_LOG_LINES: Final = 1000


def check_selection(events: list[dict[str, Any]], lab: ComposeLab) -> None:
    """Require observed alternatives and no individual reads before the operator resolves an ambiguous name."""
    assert events and events[0]["type"] == "turn.started"
    assert events[-1]["type"] == "turn.completed", events[-1]
    assert not any(row["type"] in {"answer.ready", "turn.failed"} for row in events)
    choices = [row for row in events if row["type"] == "clarification.required"]
    assert len(choices) == 1
    selection = GroupSelection.model_validate(choices[0]["selection"])
    assert {(row.kind, row.name) for row in selection.candidates} == {
        ("compose", lab.project),
        ("compose", lab.peer_project),
    }
    reads = {row["tool"] for row in events if row["type"] == "tool.started"}
    # The server may intercept inspect_group and return alternatives before reading group evidence.
    assert reads <= {"resolve_target", "request_group_selection", "list_containers", "inspect_group"}, reads


def check_language(text: str, language: str, verbatim: tuple[str, ...] = ()) -> None:
    """Require model-authored prose in the requested language without translating quoted runtime text."""
    prose = re.sub(r"```[\s\S]*?```|`[^`]*`", "", text)
    for fragment in sorted(verbatim, key=len, reverse=True):
        prose = prose.replace(fragment, "")
    prose = re.sub(r"\b[\w./:@-]*[\d_./:@-][\w./:@-]*\b", "", prose)
    prose = re.sub(
        r"\b(?:Docker|Compose|Swarm|Grafana|PostgreSQL|nginx|Telegram|Chat\s+ID|OOM|CPU|SIGKILL|SIGTERM)\b",
        "",
        prose,
        flags=re.I,
    )
    counts = {
        "ru": len(re.findall(r"[\u0430-\u044f\u0451]", prose, re.I)),
        "en": len(re.findall(r"[a-z]", prose, re.I)),
    }
    other = "en" if language == "ru" else "ru"
    assert counts[language] >= 2 and counts[language] > counts[other], f"Expected {language} narrative language: {text}"


def check_narrative(answer: DiagnosisResponse, language: str, identifiers: tuple[str, ...]) -> None:
    """Check every displayed model explanation independently while excluding raw observations and traces."""
    fields = [answer.summary]
    if answer.cause:
        fields.extend([answer.cause.immediate, *answer.cause.unknowns])
        if answer.cause.underlying:
            fields.append(answer.cause.underlying)
    for card in answer.widgets:
        if isinstance(card, ContainerStatusCard) and card.recommendation and card.recommendation.reason:
            fields.append(card.recommendation.reason)
    for text in fields:
        check_language(text, language, (*identifiers, *_verbatim_logs(answer, text)))


def _verbatim_logs(answer: DiagnosisResponse, text: str) -> tuple[str, ...]:
    """Exclude quoted or embedded observations without accepting an untranslated log as the entire explanation."""
    messages = tuple(
        entry.message for card in answer.widgets if isinstance(card, LogAnomalyCard) for entry in card.logs.entries
    )
    quotes = (("'", "'"), ('"', '"'), ("\u00ab", "\u00bb"), ("\u201c", "\u201d"))
    return (
        *(f"{left}{message}{right}" for message in messages for left, right in quotes),
        *(message for message in messages if message.rstrip(".") != text.strip().rstrip(".")),
    )


def check_answer(events: list[dict[str, Any]], lab: ComposeLab, case: Case, language: str = "en") -> DiagnosisResponse:
    """Validate typed HTTP output against exact real fixture identities and scenario facts."""
    assert events and events[0]["type"] == "turn.started"
    assert events[-1]["type"] == "turn.completed", events[-1]
    assert not any(row["type"] == "turn.failed" for row in events)
    ready = [row for row in events if row["type"] == "answer.ready"]
    assert len(ready) == 1
    answer = DiagnosisResponse.model_validate(ready[0]["answer"])
    containers = {row.id: row for row in lab.containers.values()}
    if case.spelling == "unscoped":
        containers.update(lab.peers | lab.standalone)
    assert not any(row["type"] == "clarification.required" for row in events)
    ids = set(containers)
    _check_references(answer, ids)
    names = {row.id: row.name for row in containers.values()}
    assert all(row.container_name == names.get(row.container_id or "") for row in answer.evidence)
    identifiers = (lab.project, *ids, *(row.name for row in lab.containers.values()))
    check_narrative(answer, language, identifiers)
    _check_diagnostic_scope(answer, lab, case, ids)
    _check_logs(answer, lab)
    if not case.group and case.causal_profile:
        check_causality(answer, case.causal_profile)
    return answer


def _check_diagnostic_scope(answer: DiagnosisResponse, lab: ComposeLab, case: Case, ids: set[str]) -> None:
    """Apply the selected host, group or exact-container contract to the same typed response."""
    if case.spelling == "unscoped":
        check_host(answer, lab)
        return
    check_resource_scope(answer, ids, lab.project)
    if case.group:
        _check_group(answer, lab)
    else:
        _check_container(answer, lab, case)


def _check_references(answer: DiagnosisResponse, ids: set[str]) -> None:
    """Require every displayed model reference to resolve to an observation within the fixture scope."""
    references = {row.id: row for row in answer.evidence}
    assert references
    assert all(row.host == "e2e" and row.container_id in ids | {None} for row in references.values())
    assert all(set(widget.evidence_ids) <= references.keys() for widget in answer.widgets)
    if answer.cause:
        assert set(answer.cause.evidence_ids) <= references.keys()


def check_resource_scope(answer: DiagnosisResponse, ids: set[str], project: str) -> None:
    """Reject any extra card that introduces a host, container, or group outside the real fixture."""
    for card in answer.widgets:
        if isinstance(card, ContainerStatusCard):
            _check_status_scope(card, answer, ids)
        elif isinstance(card, ComposeStackCard):
            assert card.host == "e2e"
            assert all((row.kind, row.name) == ("compose", project) for row in card.stacks)
        else:
            assert card.container_id in ids and card.host == "e2e"


def _check_status_scope(card: ContainerStatusCard, answer: DiagnosisResponse, ids: set[str]) -> None:
    """Reject state cards supported by observations belonging to a different container."""
    assert card.snapshot.id in ids and card.snapshot.host == "e2e"
    sources = {row.id: row for row in answer.evidence}
    assert card.evidence_ids
    assert all(sources[ref].container_id in {None, card.snapshot.id} for ref in card.evidence_ids)


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
        _check_causal_snapshot(snapshot, case)
    _check_uncertainty(answer, case)


def _check_causal_snapshot(snapshot: ContainerSnapshot, case: Case) -> None:
    """Keep live process state and health facts independent from the semantic narrative assertions."""
    if case.causal_profile in {"running_unhealthy", "running_history"}:
        assert snapshot.state == "running" and snapshot.restart_count == 0 and not snapshot.oom_killed
        assert snapshot.health == ("unhealthy" if case.causal_profile == "running_unhealthy" else None)
    elif case.causal_profile == "clean_shutdown":
        assert (snapshot.state, snapshot.exit_code, snapshot.oom_killed) == ("exited", 0, False)
    else:
        _check_exited(snapshot, case)


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
    if lab.case.spelling == "unscoped":
        containers.update(lab.peers)
        containers.update(lab.standalone)
    cards = [row for row in answer.widgets if isinstance(row, LogAnomalyCard)]
    assert cards, "The diagnosis omitted supported requested logs"
    for card in cards:
        assert card.host == "e2e" and card.container_id in containers
        _check_log_source(card, answer, lab.case.log_limits[0])
        raw = containers[card.container_id].logs(tail=_SOURCE_LOG_LINES).decode("utf-8", errors="replace")
        assert all(entry.message in raw for entry in card.logs.entries), "Log card contains unobserved content"


def _check_log_source(card: LogAnomalyCard, answer: DiagnosisResponse, max_lines: int) -> None:
    """Require bounded lines and exact-resource references for each log card."""
    sources = {row.id: row for row in answer.evidence}
    assert 0 < len(card.logs.entries) <= max_lines
    assert any(sources[ref].kind == "logs" for ref in card.evidence_ids)
    assert all(sources[ref].container_id in {None, card.container_id} for ref in card.evidence_ids)
