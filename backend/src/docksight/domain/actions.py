from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from docksight.domain.errors import DockSightError

type Operation = Literal["restart", "stop"]


class ActionState(StrEnum):
    PREPARED = "prepared"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"
    EXPIRED = "expired"


@dataclass
class PreparedAction:
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
        if actor != self.actor:
            raise DockSightError("action_not_found", "Action not found", 404)
        if not confirmed:
            raise DockSightError("confirmation_required", "Explicit confirmation required", 409)
        if not 3 <= len(key) <= 128:
            raise DockSightError("invalid_idempotency_key", "Invalid idempotency key", 422)
        if self.idempotency_key is not None:
            if self.idempotency_key != key:
                raise DockSightError("action_conflict", "Action uses another idempotency key", 409)

            return False
        if now >= self.expires_at:
            self.state = ActionState.EXPIRED
            raise DockSightError("action_expired", "Action has expired", 409)
        if self.state != ActionState.PREPARED:
            raise DockSightError("action_conflict", "Action cannot be executed", 409)
        self.idempotency_key = key
        self.state = ActionState.RUNNING

        return True

    def finish(self, state: ActionState, message: str) -> None:
        if self.state != ActionState.RUNNING or state not in {
            ActionState.SUCCEEDED,
            ActionState.FAILED,
            ActionState.INDETERMINATE,
        }:
            raise DockSightError("invalid_transition", "Invalid action transition", 409)
        self.state = state
        self.message = message
