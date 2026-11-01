from dataclasses import replace
from unittest.mock import Mock

import pytest

from docksight.application.views.schemas import (
    ContainerStatusCard,
    DiagnosisResponse,
    GroupLogResult,
    GroupTarget,
    HostInspection,
    HostMember,
    LogAnomalyCard,
)
from docksight.domain.diagnostics import EvidenceRef
from docksight.domain.runtime import ContainerSnapshot, LogBatch, LogEntry
from tests.fakes import snapshot
from tests.integration.live_e2e.cases import Case
from tests.integration.live_e2e.checks import check_answer
from tests.integration.live_e2e.host_checks import check_host
from tests.integration.live_e2e.lab import ComposeLab


def _observed_container(item: ContainerSnapshot) -> Mock:
    """Expose only the Docker facts and original bytes consumed by the live acceptance oracle."""
    row = Mock()
    row.id, row.name = item.id, item.name
    row.labels = {"com.docker.compose.project": item.compose_project} if item.compose_project else {}
    row.attrs = {
        "State": {"Status": item.state, "ExitCode": item.exit_code, "OOMKilled": item.oom_killed},
        "RestartCount": item.restart_count,
    }
    row.logs.return_value = b"Observed startup failure\n"
    return row


@pytest.fixture
def host_observations() -> tuple[DiagnosisResponse, ComposeLab]:
    """Provide 21 observed containers and five review candidates sharing one four-read log budget."""
    lab = object.__new__(ComposeLab)
    lab.project, lab.peer_project = "infra", "peer"
    lab.case = Case("host-oracle", ("backend",), group=True, spelling="unscoped")
    items = [
        replace(
            snapshot(),
            host="e2e",
            id=f"{index:064x}",
            name=f"worker-{index}",
            compose_project=project,
            state="exited" if index <= 5 else "running",
            exit_code=1 if index <= 4 else 0,
        )
        for index, project in enumerate(
            (lab.project, lab.project, lab.peer_project, None, *[lab.project] * 17), start=1
        )
    ]
    lab.containers = {item.id: _observed_container(item) for item in items if item.compose_project == lab.project}
    lab.peers = {items[2].id: _observed_container(items[2])}
    lab.standalone = {items[3].id: _observed_container(items[3])}
    members = [_member(item) for item in items]
    evidence = [EvidenceRef("host", "host", "e2e", None, items[0].observed_at, {})]
    widgets: list[ContainerStatusCard | LogAnomalyCard] = []
    for item in items[:4]:
        evidence.extend(
            EvidenceRef(f"{kind}-{item.id}", kind, "e2e", item.id, item.observed_at, {}, item.name)
            for kind in ("container", "logs")
        )
        widgets.extend(
            [
                ContainerStatusCard(snapshot=item, evidence_ids=[f"container-{item.id}"]),
                LogAnomalyCard(
                    host="e2e",
                    container_id=item.id,
                    evidence_ids=[f"logs-{item.id}"],
                    logs=LogBatch((LogEntry("Observed startup failure"),)),
                ),
            ]
        )
    overview = HostInspection(
        host="e2e",
        evidence_id="host",
        total=21,
        running=16,
        attention=5,
        truncated=False,
        discovery_code=None,
        members=members,
        targets=[GroupTarget(kind="compose", name=name) for name in (lab.project, lab.peer_project)],
        logs=[
            GroupLogResult(container_id=item.id, name=item.name, state="collected", evidence_id=f"logs-{item.id}")
            for item in items[:4]
        ]
        + [GroupLogResult(container_id=items[4].id, name=items[4].name, state="not_collected", code="host_log_limit")],
    )
    return DiagnosisResponse(
        summary="Five containers need inspection; the underlying causes remain unknown.",
        uncertain=True,
        host_overview=overview,
        evidence=evidence,
        widgets=widgets,
    ), lab


def _member(item: ContainerSnapshot) -> HostMember:
    """Build a canonical overview row from one independently recorded Docker snapshot."""
    return HostMember(
        container_id=item.id,
        name=item.name,
        state=item.state,
        health=item.health,
        exit_code=item.exit_code,
        oom_killed=item.oom_killed,
        restart_count=item.restart_count,
        observed_at=item.observed_at,
        group=GroupTarget(kind="compose", name=item.compose_project) if item.compose_project else None,
        attention=item.state != "running",
    )


def test_host_oracle_accepts_observed_membership_and_original_log_bytes(
    host_observations: tuple[DiagnosisResponse, ComposeLab],
) -> None:
    answer, lab = host_observations
    check_answer(
        [{"type": "turn.started"}, {"type": "answer.ready", "answer": answer.model_dump()}, {"type": "turn.completed"}],
        lab,
        lab.case,
    )


@pytest.mark.parametrize("field", ["coverage", "reason", "name", "evidence"])
def test_host_oracle_rejects_missing_or_invented_fifth_candidate_coverage(
    host_observations: tuple[DiagnosisResponse, ComposeLab], field: str
) -> None:
    answer, lab = host_observations
    assert answer.host_overview is not None
    check_host(answer, lab)
    result = answer.host_overview.logs[-1]
    if field == "coverage":
        answer.host_overview.logs.pop()
    elif field == "reason":
        result.code = "invented_limit"
    elif field == "name":
        result.name = "invented-container"
    else:
        result.evidence_id = "invented-evidence"
    with pytest.raises(AssertionError):
        check_host(answer, lab)


def test_host_log_oracle_accepts_more_than_the_old_thirty_line_limit(
    host_observations: tuple[DiagnosisResponse, ComposeLab],
) -> None:
    answer, lab = host_observations
    card = next(row for row in answer.widgets if isinstance(row, LogAnomalyCard))
    card.logs = LogBatch(tuple(LogEntry("Observed startup failure") for _ in range(40)))
    check_answer(
        [{"type": "turn.started"}, {"type": "answer.ready", "answer": answer.model_dump()}, {"type": "turn.completed"}],
        lab,
        lab.case,
    )


def test_host_oracle_accepts_a_fifth_log_read_explicitly_requested_after_the_automatic_budget(
    host_observations: tuple[DiagnosisResponse, ComposeLab],
) -> None:
    answer, lab = host_observations
    assert answer.host_overview is not None
    pending = answer.host_overview.logs[-1]
    first = next(row.snapshot for row in answer.widgets if isinstance(row, ContainerStatusCard))
    item = replace(first, id=pending.container_id, name=pending.name, exit_code=0)
    answer.evidence.extend(
        EvidenceRef(f"{kind}-{item.id}", kind, "e2e", item.id, item.observed_at, {}, item.name)
        for kind in ("container", "logs")
    )
    answer.widgets.extend(
        [
            ContainerStatusCard(snapshot=item, evidence_ids=[f"container-{item.id}"]),
            LogAnomalyCard(
                host="e2e",
                container_id=item.id,
                evidence_ids=[f"logs-{item.id}"],
                logs=LogBatch((LogEntry("Observed startup failure"),)),
            ),
        ]
    )
    answer.host_overview.logs[-1] = GroupLogResult(
        container_id=item.id, name=item.name, state="collected", evidence_id=f"logs-{item.id}"
    )
    check_host(answer, lab)


@pytest.mark.parametrize("field", ["total", "running", "attention"])
def test_host_oracle_rejects_model_invented_host_counts(
    host_observations: tuple[DiagnosisResponse, ComposeLab],
    field: str,
) -> None:
    answer, lab = host_observations
    assert answer.host_overview is not None
    setattr(answer.host_overview, field, 20)
    with pytest.raises(AssertionError):
        check_host(answer, lab)


@pytest.mark.parametrize("field", ["state", "group", "membership", "primary", "log_source", "status_card", "log_card"])
def test_host_oracle_rejects_wrong_membership_provenance_and_omitted_details(
    host_observations: tuple[DiagnosisResponse, ComposeLab],
    field: str,
) -> None:
    answer, lab = host_observations
    assert answer.host_overview is not None
    overview = answer.host_overview
    if field == "state":
        overview.members[0].state = "running"
    elif field == "group":
        overview.members[0].group = GroupTarget(kind="compose", name=lab.peer_project)
    elif field == "membership":
        overview.members.pop()
    elif field == "primary":
        answer.evidence[0] = replace(answer.evidence[0], container_id=overview.members[0].container_id)
    elif field == "log_source":
        answer.evidence[2] = replace(answer.evidence[2], container_id=overview.members[1].container_id)
    else:
        answer.widgets.pop(0 if field == "status_card" else 1)
    with pytest.raises(AssertionError):
        check_host(answer, lab)


def test_host_oracle_rejects_a_log_message_absent_from_the_original_container(
    host_observations: tuple[DiagnosisResponse, ComposeLab],
) -> None:
    answer, lab = host_observations
    card = next(row for row in answer.widgets if isinstance(row, LogAnomalyCard))
    card.logs = LogBatch((LogEntry("Invented database outage"),))
    with pytest.raises(AssertionError, match="unobserved"):
        check_answer(
            [
                {"type": "turn.started"},
                {"type": "answer.ready", "answer": answer.model_dump()},
                {"type": "turn.completed"},
            ],
            lab,
            lab.case,
        )
