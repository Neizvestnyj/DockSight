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


def test_live_follow_up(
    api: httpx.Client,
    lab: ComposeLab,
    case: Case,
    language: Language,
    model_name: str,
    artifacts: Path,
) -> None:
    """Continue one real session from a group failure to an exact dependency sharing its project's name."""
    first_events: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
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
        payload = {"host": "e2e", "query": query, "session_id": first_events[0]["session_id"]}
        _read_turn(api, payload, events)
        assert events[0]["session_id"] == first_events[0]["session_id"]
        _check_follow_up(events, lab, language)
        assert original.group and original.group.summary.name == lab.project
        assert {row.id for row in original.group.summary.members} == {row.id for row in lab.containers.values()}
    finally:
        record_run(
            report_path(artifacts, model_name, case, language),
            lab,
            model_name,
            started,
            payload,
            events,
            previous_turn={"input": first_input, "events": first_events},
        )


def _check_follow_up(events: list[dict[str, Any]], lab: ComposeLab, language: Language) -> None:
    """Compare fresh dependency cards with Docker, rejecting inherited group cards or old evidence scope."""
    assert events[-1]["type"] == "turn.completed", events[-1]
    assert not any(event["type"] in {"turn.failed", "clarification.required"} for event in events)
    ready = [event for event in events if event["type"] == "answer.ready"]
    assert len(ready) == 1
    answer = DiagnosisResponse.model_validate(ready[0]["answer"])
    peer = next(iter(lab.peers.values()))
    assert answer.group is None
    check_resource_scope(answer, {peer.id}, lab.peer_project)
    check_narrative(answer, language, (peer.id, peer.name, lab.project))
    states = [row for row in answer.widgets if isinstance(row, ContainerStatusCard)]
    logs = [row for row in answer.widgets if isinstance(row, LogAnomalyCard)]
    assert len(states) == len(logs) == 1
    assert states[0].snapshot.state == peer.attrs["State"]["Status"] == "exited"
    assert states[0].snapshot.exit_code == peer.attrs["State"]["ExitCode"] == 1
    assert answer.evidence and all(row.host == "e2e" and row.container_id == peer.id for row in answer.evidence)
    refs = {row.id for row in answer.evidence}
    assert all(set(row.evidence_ids) <= refs for row in answer.widgets)
    observed = peer.logs(tail=100).decode("utf-8", errors="replace")
    assert logs[0].logs.entries and all(entry.message in observed for entry in logs[0].logs.entries)
