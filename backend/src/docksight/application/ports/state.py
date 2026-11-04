from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from docksight.domain.actions import ActionState, PreparedAction
from docksight.domain.diagnostics import JsonObject


@dataclass(frozen=True)
class StoredAction:
    """Return a detached domain value and its explicit persisted transition position."""

    action: PreparedAction
    revision: int
    phase: Literal["prepared", "claimed", "dispatching", "terminal"]


@dataclass(frozen=True)
class ActionClaim:
    """Identify whether this admission created a claim or found its retained outcome."""

    stored: StoredAction
    claimed: bool


class ReconciliationObservation(BaseModel):
    """Retain only a fresh sanitized exact-target Docker observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    host: str = Field(min_length=1, max_length=128)
    container_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed_at: AwareDatetime
    exists: bool
    fingerprint: str | None = Field(default=None, min_length=1, max_length=256)
    state: str | None = Field(default=None, min_length=1, max_length=32)


class BlockedTarget(BaseModel):
    """Expose the guard revision and unresolved action identities for offline review."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    action_id: str = Field(min_length=1, max_length=36)
    host: str = Field(min_length=1, max_length=128)
    container_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision: int = Field(ge=0)
    blocked: bool
    unresolved_actions: tuple[str, ...] = Field(max_length=1000)
    observation: ReconciliationObservation | None = None


class ReconcileTarget(BaseModel):
    """Require an exact guard confirmation and accountable unknown-outcome acknowledgement."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    action_id: str = Field(min_length=1, max_length=36)
    expected_revision: int = Field(ge=0)
    confirm_target: str = Field(min_length=66, max_length=193)
    actor: str = Field(min_length=1, max_length=128)
    operator: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=1000)
    acknowledge_unknown_outcome: bool


class ActionStore(Protocol):
    """Persist detached action transitions, authoritative audit, and exact-target guards atomically."""

    async def add(self, action: PreparedAction, now: datetime) -> StoredAction:
        """Retain a newly prepared action within storage capacity."""
        ...

    async def get(self, action_id: str, actor: str, now: datetime) -> StoredAction:
        """Resolve an action only within its actor's scope."""
        ...

    async def claim(
        self,
        action_id: str,
        actor: str,
        key: str,
        confirmed: bool,
        now: datetime,
    ) -> ActionClaim:
        """Atomically validate confirmation, expiry, ownership, and idempotency."""
        ...

    async def mark_dispatch(self, action_id: str, expected_revision: int, now: datetime) -> StoredAction:
        """Commit dispatch intent and audit before any Docker mutation can be sent."""
        ...

    async def complete(
        self, action_id: str, expected_revision: int, state: ActionState, message: str, now: datetime
    ) -> StoredAction:
        """Save a legal terminal outcome, audit, and guard release or block together."""
        ...

    async def inspect_block(self, action_id: str) -> BlockedTarget:
        """Read exact blocked target protection without changing any action lifecycle."""
        ...

    async def reconcile(
        self, command: ReconcileTarget, observation: ReconciliationObservation, now: datetime
    ) -> BlockedTarget:
        """Audit explicit reconciliation and invalidate stale preparations without rewriting the old outcome."""
        ...


class AuditPort(Protocol):
    """Define emission of sanitized action audit events."""

    async def record(self, event: str, data: JsonObject) -> None:
        """Record an action event or raise when the audit output is unavailable."""
        ...


type EventStream = AsyncIterator[JsonObject]
