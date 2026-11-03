from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from docksight.domain.errors import DockSightError, ErrorKind
from docksight.domain.runtime import ContainerState

type Operation = Literal["restart", "stop"]


def allowed_operations(state: ContainerState) -> tuple[Operation, ...]:
    """Return the mutations permitted by the observed container lifecycle state."""
    if state == "running":
        return ("restart", "stop")
    if state in {"created", "exited"}:
        return ("restart",)
    if state == "restarting":
        return ("stop",)

    return ()


class ActionState(StrEnum):
    """Enumerate preparation, execution, expiry, and terminal action outcomes."""

    PREPARED = "prepared"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"
    EXPIRED = "expired"


@dataclass
class PreparedAction:
    """Bind an expiring mutation to its owner, exact target, and observed fingerprint."""

    id: str
    actor: str
    host: str
    container_id: str
    operation: Operation
    fingerprint: str
    expires_at: datetime
    state: ActionState = ActionState.PREPARED
    idempotency_key: str | None = None
    message: str = "Confirmation required"

    def claim(self, actor: str, key: str, confirmed: bool, now: datetime) -> bool:
        """Validate ownership and confirmation before claiming one idempotent execution."""
        if actor != self.actor:
            raise DockSightError("action_not_found", "Action not found", ErrorKind.NOT_FOUND)
        if not confirmed:
            raise DockSightError("confirmation_required", "Explicit confirmation required", ErrorKind.CONFLICT)
        if not 3 <= len(key) <= 128:
            raise DockSightError("invalid_idempotency_key", "Invalid idempotency key", ErrorKind.VALIDATION)
        if self.idempotency_key is not None:
            if self.idempotency_key != key:
                raise DockSightError("action_conflict", "Action uses another idempotency key", ErrorKind.CONFLICT)

            return False
        if now >= self.expires_at:
            self.state = ActionState.EXPIRED
            raise DockSightError("action_expired", "Action has expired", ErrorKind.CONFLICT)
        if self.state != ActionState.PREPARED:
            raise DockSightError("action_conflict", "Action cannot be executed", ErrorKind.CONFLICT)
        self.idempotency_key = key
        self.state = ActionState.RUNNING

        return True

    def finish(self, state: ActionState, message: str) -> None:
        """Allow a running action to enter a valid terminal execution state once."""
        if self.state != ActionState.RUNNING or state not in {
            ActionState.SUCCEEDED,
            ActionState.FAILED,
            ActionState.INDETERMINATE,
        }:
            raise DockSightError("invalid_transition", "Invalid action transition", ErrorKind.CONFLICT)
        self.state = state
        self.message = message
