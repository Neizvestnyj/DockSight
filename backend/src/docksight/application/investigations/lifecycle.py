import hashlib
import json
from datetime import datetime
from uuid import uuid4

from docksight.application.investigations.contracts import (
    ClarificationTurn,
    InvestigationWorkspace,
    SavedTurn,
    StartTurn,
    TurnOutcome,
    TurnUpdate,
)
from docksight.application.investigations.errors import HistoryError, WorkspaceConflict
from docksight.application.ports.models import ModelMessage
from docksight.domain.errors import ErrorKind


def conflict(code: str = "turn_conflict", message: str = "Diagnostic turn has changed") -> HistoryError:
    """Return a safe lifecycle conflict without reflecting input or stored payloads."""
    return HistoryError(code, message, ErrorKind.CONFLICT)


def input_digest(command: StartTurn) -> str:
    """Hash submitted logical input before redaction, default resolution, or mutable admission checks."""
    submitted = command.root
    value = submitted.model_dump(
        mode="json", exclude={"submission_id", "expected_revision", "expected_parent_revision", "kind"}
    )
    if "query" in value:
        value["query"] = str(value["query"]).strip()
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def accepted_snapshot(
    actor: str,
    host: str,
    command: StartTurn,
    workspace: InvestigationWorkspace,
    parent: SavedTurn | None,
    request_id: str,
    now: datetime,
) -> SavedTurn:
    """Build the next detached turn only after validating workspace and clarification invariants."""
    submitted = command.root
    if workspace.revision != submitted.expected_revision:
        raise WorkspaceConflict(workspace.model_copy(deep=True))
    query = submitted.query if not isinstance(submitted, ClarificationTurn) else _parent_query(submitted, parent, host)
    return SavedTurn(
        id=str(uuid4()),
        investigation_id=submitted.investigation_id,
        actor=actor,
        host=host,
        submission_id=submitted.submission_id,
        request_id=request_id,
        query=query,
        target=submitted.target,
        model=submitted.model,
        clarification_of=submitted.clarification_of if isinstance(submitted, ClarificationTurn) else None,
        state="running",
        created_at=now,
        updated_at=now,
    )


def accepted_workspace(workspace: InvestigationWorkspace, saved: SavedTurn) -> InvestigationWorkspace:
    """Advance admission revision and clear only the acknowledged draft submitted as this question."""
    draft = workspace.draft
    if saved.clarification_of is None and draft.strip() == saved.query:
        draft = ""
    return workspace.model_copy(update={"revision": workspace.revision + 1, "draft": draft})


def _parent_query(submitted: ClarificationTurn, parent: SavedTurn | None, host: str) -> str:
    """Accept one exact persisted candidate and retain its original sanitized question."""
    if (
        parent is None
        or parent.investigation_id != submitted.investigation_id
        or parent.host != host
        or parent.state != "awaiting_selection"
        or parent.resolved_by_turn_id is not None
        or parent.revision != submitted.expected_parent_revision
    ):
        raise conflict("clarification_conflict", "Clarification has changed or was already resolved")
    if parent.selection is None or submitted.target not in parent.selection.candidates:
        raise conflict("invalid_target", "Choose one of the saved clarification candidates")
    return parent.query


def updated_snapshot(current: SavedTurn, update: TurnUpdate, now: datetime) -> SavedTurn:
    """Compare revision and replace only bounded nonterminal observations."""
    _running(current, update.expected_revision)
    return SavedTurn.model_validate(
        current.model_dump()
        | update.model_dump(exclude={"expected_revision"})
        | {"revision": current.revision + 1, "updated_at": now}
    )


def finished_snapshot(current: SavedTurn, outcome: TurnOutcome, now: datetime) -> SavedTurn:
    """Compare revision and validate the terminal state's result shape."""
    _running(current, outcome.expected_revision)
    if (outcome.state == "completed") != (outcome.answer is not None):
        raise conflict(message="Completed turns require a validated answer")
    if (outcome.state == "awaiting_selection") != (outcome.selection is not None):
        raise conflict(message="Clarification turns require saved candidates")
    return SavedTurn.model_validate(
        current.model_dump()
        | outcome.model_dump(exclude={"expected_revision"})
        | {"revision": current.revision + 1, "updated_at": now, "finished_at": now}
    )


def _running(current: SavedTurn, revision: int) -> None:
    """Reject stale writes and second terminal transitions through the same CAS boundary."""
    if current.state != "running" or current.revision != revision:
        raise conflict()


def append_context(context: tuple[ModelMessage, ...], saved: SavedTurn) -> tuple[ModelMessage, ...]:
    """Keep at most ten whole successful question/summary pairs and 32,000 text characters."""
    if saved.state != "completed" or saved.answer is None:
        return context
    result = (*context, ModelMessage("user", saved.query), ModelMessage("assistant", saved.answer.summary))
    while len(result) > 20 or sum(len(message.content) for message in result) > 32000:
        result = result[2:]
    return result
