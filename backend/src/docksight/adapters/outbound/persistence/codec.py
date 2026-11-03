import base64
import hashlib
import json
from datetime import UTC, datetime
from typing import Literal, cast

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from docksight.application.investigations.contracts import (
    ActorWorkspace,
    ActorWorkspacePatch,
    InvestigationWorkspace,
    SavedTurn,
    WorkspacePatch,
)
from docksight.application.investigations.errors import HistoryError, WorkspaceConflict
from docksight.domain.actions import ActionState, Operation, PreparedAction
from docksight.domain.errors import ErrorKind


class ActionSnapshot(BaseModel):
    """Validate a bounded versioned domain snapshot independently of indexed lifecycle fields."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1, max_length=36)
    actor: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=128)
    container_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    operation: Operation
    fingerprint: str = Field(min_length=1, max_length=256)
    expires_at: AwareDatetime
    state: ActionState
    idempotency_key: str | None = Field(default=None, min_length=3, max_length=128)
    message: str = Field(min_length=1, max_length=2000)


def encode_action(action: PreparedAction) -> str:
    """Reject invalid action values before writing the bounded versioned envelope."""
    return ActionSnapshot.model_validate(action).model_dump_json()


def decode_action(encoded: str) -> PreparedAction:
    """Hydrate only a supported detached domain action without ORM references."""
    value = decode_value(ActionSnapshot, encoded)
    return PreparedAction(
        value.id,
        value.actor,
        value.host,
        value.container_id,
        value.operation,
        value.fingerprint,
        value.expires_at,
        value.state,
        value.idempotency_key,
        value.message,
    )


def utc_text(value: datetime) -> str:
    """Normalize aware timestamps so lexical keyset ordering matches chronological ordering."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoryError("history_invalid", "History timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def patch_value[W: (ActorWorkspace, InvestigationWorkspace)](
    current: W, patch: ActorWorkspacePatch | WorkspacePatch
) -> W:
    """Validate a detached workspace replacement after comparing its acknowledged revision."""
    if current.revision != patch.expected_revision:
        raise WorkspaceConflict(current.model_copy(deep=True))
    values = current.model_dump()
    values.update(patch.model_dump(exclude_unset=True, exclude={"expected_revision"}))
    values["revision"] = current.revision + 1
    return type(current).model_validate(values)


def decode_value[T: BaseModel](contract: type[T], encoded: str) -> T:
    """Translate invalid persisted envelopes into a safe typed per-item failure."""
    try:
        return contract.model_validate_json(encoded)
    except (ValidationError, ValueError) as error:
        raise HistoryError("history_unsupported", "Saved history format is unsupported", ErrorKind.CONFLICT) from error


def decode_turn(encoded: str) -> SavedTurn:
    """Dispatch supported public snapshot versions without silently deleting unknown versions."""
    return decode_value(SavedTurn, encoded)


def page_limit(value: int) -> int:
    """Bound archive query work even when called outside an HTTP transport."""
    if not 1 <= value <= 50:
        raise HistoryError("history_cursor", "History page limit must be between 1 and 50")
    return value


def _scope(actor: str, query: str) -> str:
    """Bind an opaque cursor to actor and query without exposing actor names in its payload."""
    return hashlib.sha256(json.dumps([actor, query], separators=(",", ":")).encode()).hexdigest()


def encode_cursor(actor: str, query: str, timestamp: str, identity: str) -> str:
    """Encode bounded keyset coordinates scoped to their original actor and history query."""
    payload = json.dumps([_scope(actor, query), timestamp, identity], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(actor: str, query: str, cursor: str | None) -> tuple[str, str] | None:
    """Reject malformed or cross-scope cursors before querying saved content."""
    if cursor is None:
        return None
    try:
        if len(cursor) > 1024:
            raise ValueError("Cursor is too long")
        values: object = json.loads(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True))
        if not isinstance(values, list):
            raise ValueError("Invalid cursor fields")
        fields = cast(list[object], values)
        if len(fields) != 3 or not all(isinstance(value, str) for value in fields):
            raise ValueError("Invalid cursor fields")
        scope, timestamp, identity = cast(list[str], fields)
        if scope != _scope(actor, query):
            raise ValueError("Cursor scope differs")
        return str(timestamp), str(identity)
    except (ValueError, UnicodeError) as error:
        raise HistoryError("history_cursor", "History cursor is invalid for this query") from error
