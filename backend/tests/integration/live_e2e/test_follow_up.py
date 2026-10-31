from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from docksight.application.views.schemas import ContainerStatusCard, DiagnosisResponse, LogAnomalyCard
from tests.integration.live_e2e.cases import Case, Language
from tests.integration.live_e2e.checks import check_answer, check_narrative, check_resource_scope
from tests.integration.live_e2e.lab import ComposeLab
from tests.integration.live_e2e.reports import record_run, report_path
from tests.integration.live_e2e.test_diagnostics import _read_turn

pytestmark = [pytest.mark.live, pytest.mark.docker]


@pytest.mark.parametrize("clarify", [False, True], ids=["explicit-container", "mixed-clarification"])
def test_live_follow_up(
    api: httpx.Client,
    lab: ComposeLab,
    case: Case,
    language: Language,
    model_name: str,
    artifacts: Path,
    clarify: bool,
) -> None:
    """Continue a real group investigation through typed or clarified same-name dependency selection."""
    first_events: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    clarification: list[dict[str, Any]] = []
    first_input = {"host": "e2e", "query": case.query(lab.project, "", language)}
    payload: dict[str, Any] = {}
    started = datetime.now(UTC).isoformat()
    try:
        _read_turn(api, first_input, first_events)
        original = check_answer(first_events, lab, case, language)
        peer = next(iter(lab.peers.values()))
        assert peer.name == lab.peer_project == peer.labels["com.docker.compose.project"]
        query = (
            f"Может зависимость просто не запущена? Есть же контейнер {peer.name}. Проверь состояние и логи."
            if language == "ru"
            else f"Could the dependency simply be stopped? Check container {peer.name}, its state and logs."
        )
        if clarify:
            query = (
                f"\u0410 может потому-что {peer.name} не запущен?"
                if language == "ru"
                else f"Could {peer.name} simply be stopped?"
            )
        payload = {"host": "e2e", "query": query, "session_id": first_events[0]["session_id"]}
        if clarify:
            _select_dependency(api, payload, clarification, lab)
            payload["container_id"] = peer.id
        _read_turn(api, payload, events)
        assert events[0]["session_id"] == first_events[0]["session_id"]
        _check_follow_up(events, lab, language)
        assert original.group and original.group.summary.name == lab.project
        assert {row.id for row in original.group.summary.members} == {row.id for row in lab.containers.values()}
    finally:
        record_run(
            report_path(artifacts, model_name, case, language, "mixed" if clarify else "explicit"),
            lab,
            model_name,
            started,
            payload,
            events,
            clarification_events=clarification,
            previous_turn={"input": first_input, "events": first_events},
        )


def _select_dependency(
    api: httpx.Client, payload: dict[str, Any], events: list[dict[str, Any]], lab: ComposeLab
) -> None:
    """Verify real same-name alternatives are returned without asking a model to guess."""
    _read_turn(api, payload, events)
    assert events[-1]["type"] == "turn.completed"
    assert not any(row["type"] in {"turn.failed", "answer.ready"} for row in events)
    assert not any(row["type"] == "trace.step" and row["step"]["kind"] == "model" for row in events)
    peer = next(iter(lab.peers.values()))
    selection = next(row["selection"] for row in events if row["type"] == "clarification.required")
    assert selection["candidates"] == [
        {"kind": "container", "id": peer.id, "name": peer.name},
        {"kind": "compose", "name": lab.peer_project},
    ]


def _check_follow_up(
    events: list[dict[str, Any]], lab: ComposeLab, language: Language, group: bool = False
) -> DiagnosisResponse:
    """Compare fresh dependency cards with Docker, rejecting inherited group cards or old evidence scope."""
    assert events[-1]["type"] == "turn.completed", events[-1]
    assert not any(event["type"] in {"turn.failed", "clarification.required"} for event in events)
    ready = [event for event in events if event["type"] == "answer.ready"]
    assert len(ready) == 1
    answer = DiagnosisResponse.model_validate(ready[0]["answer"])
    peer = next(iter(lab.peers.values()))
    if group:
        assert answer.group and answer.group.summary.name == lab.peer_project
        assert answer.group.summary.total == 1 and answer.group.summary.running == 0
    else:
        assert answer.group is None
    check_resource_scope(answer, {peer.id}, lab.peer_project)
    check_narrative(answer, language, (peer.id, peer.name, lab.project))
    _check_dependency_details(answer, lab)
    return answer


def _check_dependency_details(answer: DiagnosisResponse, lab: ComposeLab) -> None:
    """Require fresh exact-resource cards and the actual final Docker line, even when the batch is truncated."""
    peer = next(iter(lab.peers.values()))
    states = [row for row in answer.widgets if isinstance(row, ContainerStatusCard)]
    logs = [row for row in answer.widgets if isinstance(row, LogAnomalyCard)]
    assert len(states) == len(logs) == 1
    assert states[0].snapshot.state == peer.attrs["State"]["Status"]
    assert states[0].snapshot.exit_code == peer.attrs["State"]["ExitCode"]
    assert answer.evidence and all(row.host == "e2e" and row.container_id in {peer.id, None} for row in answer.evidence)
    refs = {row.id for row in answer.evidence}
    assert all(set(row.evidence_ids) <= refs for row in answer.widgets)
    observed = peer.logs(tail=200).decode("utf-8", errors="replace")
    assert logs[0].logs.entries and all(entry.message in observed for entry in logs[0].logs.entries)
    assert logs[0].logs.entries[-1].message == observed.splitlines()[-1]


def _check_shutdown_cause(answer: DiagnosisResponse) -> None:
    """Require uncertainty about the stop initiator and reject transaction errors as the immediate stop cause."""
    if answer.cause:
        assert answer.cause.underlying is None
        assert answer.cause.unknowns
        immediate = answer.cause.immediate.casefold()
        assert not any(
            term in immediate
            for term in ("foreign key", "unique constraint", "integrity", "внешн", "уникальн", "целостност")
        )
    else:
        assert answer.uncertain


def test_live_shutdown_group_follow_up(
    api: httpx.Client, lab: ComposeLab, case: Case, language: Language, model_name: str, artifacts: Path
) -> None:
    """Investigate a cleanly stopped dependency group after SQL-error history, preserving the final shutdown lines."""
    first_events: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    started = datetime.now(UTC).isoformat()
    first_input = {"host": "e2e", "query": case.query(lab.project, "", language)}
    payload: dict[str, Any] = {}
    try:
        _read_turn(api, first_input, first_events)
        check_answer(first_events, lab, case, language)
        query = (
            f"Проверь, связано ли это \u0441 Compose {lab.peer_project}."
            if language == "ru"
            else f"Check whether this is related to Compose {lab.peer_project}."
        )
        payload = {"host": "e2e", "query": query, "session_id": first_events[0]["session_id"]}
        _read_turn(api, payload, events)
        answer = _check_follow_up(events, lab, language, group=True)
        _check_shutdown_cause(answer)
    finally:
        record_run(
            report_path(artifacts, model_name, case, language, "shutdown-group"),
            lab,
            model_name,
            started,
            payload,
            events,
            previous_turn={"input": first_input, "events": first_events},
        )
