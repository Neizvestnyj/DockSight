from datetime import UTC, datetime
from uuid import uuid4

import pytest

from docksight.application.diagnostics.trace import TraceStep
from docksight.application.investigations.contracts import SavedTurn
from docksight.application.investigations.errors import HistoryError
from docksight.application.investigations.observations import TurnObservations
from docksight.application.redaction import Redactor


def snapshot() -> SavedTurn:
    """Provide an independently owned running snapshot for event normalization tests."""
    return SavedTurn(
        id=str(uuid4()),
        investigation_id=str(uuid4()),
        actor="alice",
        host="local",
        submission_id=str(uuid4()),
        request_id="req",
        query="Inspect",
        state="running",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_progress_caps_entries_and_redacts_names_without_retaining_tool_arguments() -> None:
    saved = snapshot()
    observations = TurnObservations(Redactor(secrets=("private-token",)))
    for index in range(101):
        update = observations.consume(
            {"type": "tool.started", "turn_id": saved.id, "tool": f"private-token-{index}"}, saved
        )
        assert update is not None
        saved = SavedTurn.model_validate(saved.model_dump() | update.model_dump(exclude={"expected_revision"}))
    assert len(saved.progress) == 100 and saved.progress_truncated
    assert "private-token" not in saved.model_dump_json()
    update = observations.consume(
        {"type": "tool.completed", "turn_id": saved.id, "tool": "private-token-99", "ok": False}, saved
    )
    assert update is not None and update.progress[-1].state == "failed"


def test_saved_trace_omits_previews_and_rejects_overflow_instead_of_silent_truncation() -> None:
    saved = snapshot()
    observations = TurnObservations(Redactor(secrets=("private-token",)))
    for index in range(133):
        step = TraceStep(
            id=f"step-{index}",
            kind="model",
            operation="private-token",
            started_at=datetime.now(UTC),
            response="prompt reasoning private-token",
            response_truncated=True,
        )
        update = observations.consume(
            {"type": "trace.step", "turn_id": saved.id, "step": step.model_dump(mode="json")}, saved
        )
        assert update is not None
        saved = SavedTurn.model_validate(saved.model_dump() | update.model_dump(exclude={"expected_revision"}))
    assert len(saved.trace) == 133
    assert "private-token" not in saved.model_dump_json() and "prompt reasoning" not in saved.model_dump_json()
    with pytest.raises(HistoryError) as caught:
        observations.consume(
            {
                "type": "trace.step",
                "turn_id": saved.id,
                "step": step.model_copy(update={"id": "step-next"}).model_dump(mode="json"),
            },
            saved,
        )
    assert caught.value.code == "history_capacity"


def test_error_and_clarification_outcomes_do_not_return_buffered_answers() -> None:
    saved = snapshot()
    observations = TurnObservations(Redactor())
    assert observations.outcome(0).state == "failed"
    observations.consume(
        {
            "type": "clarification.required",
            "turn_id": saved.id,
            "selection": {"candidates": [{"kind": "compose", "name": "web"}]},
        },
        saved,
    )
    assert observations.outcome(0).state == "awaiting_selection"
    observations.consume(
        {"type": "turn.failed", "turn_id": saved.id, "code": "dependency_failed", "message": "Dependency unavailable"},
        saved,
    )
    assert observations.outcome(0).state == "failed"
