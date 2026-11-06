from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from docksight.application.action_reconciliation import validate_reconciliation
from docksight.application.investigations.errors import StorageError
from docksight.application.ports.state import (
    ActionClaim,
    ActionOrigin,
    BlockedTarget,
    ReconcileTarget,
    ReconciliationObservation,
    StoredAction,
)
from docksight.domain.actions import ActionState, PreparedAction
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError, ErrorKind


@dataclass(frozen=True)
class _Guard:
    """Retain one exact target reservation independently of action preparation cleanup."""

    active: str | None = None
    blocked: str | None = None
    revision: int = 0


def _detached(stored: StoredAction) -> StoredAction:
    """Prevent callers from changing retained state through a domain reference."""
    return replace(stored, action=replace(stored.action))


class MemoryActions:
    """Keep explicit atomic transitions and guards with weaker process-restart guarantees."""

    def __init__(
        self,
        capacity: int = 1000,
        retention: int = 86400,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Bound live preparations while retaining claimed outcomes and audit indefinitely."""
        self._entries: dict[str, StoredAction] = {}
        self._guards: dict[tuple[str, str], _Guard] = {}
        self._audit: list[tuple[str, JsonObject]] = []
        self._origins: dict[str, ActionOrigin] = {}
        self._capacity = capacity
        self._retention = timedelta(seconds=retention)
        self._clock = clock
        self._healthy = True

    def _append_audit(self, event: str, action: PreparedAction, now: datetime, extra: JsonObject | None = None) -> None:
        """Append authoritative memory audit before publishing the matching state change."""
        origin = self._origins.get(action.id)
        self._audit.append(
            (
                event,
                {
                    "action_id": action.id,
                    "actor": action.actor,
                    "host": action.host,
                    "container_id": action.container_id,
                    "operation": action.operation,
                    "occurred_at": now.isoformat(),
                    "request_id": origin.request_id if origin else None,
                    "turn_id": origin.turn_id if origin else None,
                    **(extra or {}),
                },
            )
        )

    def _save(self, stored: StoredAction, event: str, now: datetime, guard: _Guard | None = None) -> StoredAction:
        """Publish an action and its guard only after its authoritative audit append succeeds."""
        if not self._healthy:
            raise StorageError()
        try:
            self._append_audit(event, stored.action, now)
        except Exception as error:
            self._healthy = False
            raise StorageError() from error
        self._entries[stored.action.id] = _detached(stored)
        if guard is not None:
            self._guards[(stored.action.host, stored.action.container_id)] = guard
        return _detached(stored)

    async def add(self, action: PreparedAction, now: datetime, origin: ActionOrigin | None = None) -> StoredAction:
        """Retain preparation and audit without evicting claimed execution protection."""
        if action.id in self._entries:
            raise DockSightError("action_conflict", "Action already exists", ErrorKind.CONFLICT)
        removable = [
            key
            for key, item in self._entries.items()
            if item.action.idempotency_key is None and now >= item.action.expires_at + self._retention
        ]
        for key in removable:
            del self._entries[key]
        live = sum(
            item.action.state == ActionState.PREPARED and item.action.expires_at > now
            for item in self._entries.values()
        )
        if live >= self._capacity:
            raise DockSightError("action_capacity", "Action capacity reached; retry later", ErrorKind.UNAVAILABLE)
        if origin is not None:
            self._origins[action.id] = origin
        return self._save(StoredAction(replace(action), 0, "prepared"), "action.prepared", now)

    async def get(self, action_id: str, actor: str, now: datetime) -> StoredAction:
        """Return an owned detached value and durably expire an unclaimed preparation."""
        item = self._entries.get(action_id)
        if item is None or item.action.actor != actor:
            raise DockSightError("action_not_found", "Action not found", ErrorKind.NOT_FOUND)
        item = _detached(item)
        if item.action.expire(now):
            return self._save(replace(item, revision=item.revision + 1, phase="terminal"), "action.expired", now)
        guard = self._guards.get((item.action.host, item.action.container_id), _Guard())
        if item.action.state == ActionState.PREPARED and guard.blocked:
            raise DockSightError(
                "target_indeterminate", "Inspect Docker and reconcile the previous action", ErrorKind.CONFLICT
            )
        return item

    async def claim(self, action_id: str, actor: str, key: str, confirmed: bool, now: datetime) -> ActionClaim:
        """Validate the domain claim and reserve an unblocked exact target atomically."""
        item = await self.get(action_id, actor, now)
        if not item.action.claim(actor, key, confirmed, now):
            return ActionClaim(item, False)
        guard = self._guards.get((item.action.host, item.action.container_id), _Guard())
        _available(guard)
        return ActionClaim(
            self._save(
                replace(item, revision=item.revision + 1, phase="claimed"),
                "action.claimed",
                now,
                replace(guard, active=action_id, revision=guard.revision + 1),
            ),
            True,
        )

    def _transition(self, action_id: str, revision: int) -> tuple[StoredAction, _Guard]:
        """Require the exact persisted revision and its still-owned active reservation."""
        item = self._entries.get(action_id)
        if item is None or item.revision != revision:
            raise DockSightError("action_conflict", "Action revision changed", ErrorKind.CONFLICT)
        guard = self._guards.get((item.action.host, item.action.container_id), _Guard())
        if guard.active != action_id:
            raise DockSightError("action_conflict", "Action no longer owns the target", ErrorKind.CONFLICT)
        return _detached(item), guard

    async def mark_dispatch(self, action_id: str, expected_revision: int, now: datetime) -> StoredAction:
        """Persist dispatch intent before handing the mutation to Docker."""
        item, _ = self._transition(action_id, expected_revision)
        if item.phase != "claimed":
            raise DockSightError("action_conflict", "Action was already dispatched", ErrorKind.CONFLICT)
        return self._save(replace(item, revision=item.revision + 1, phase="dispatching"), "action.dispatching", now)

    async def complete(
        self, action_id: str, expected_revision: int, state: ActionState, message: str, now: datetime
    ) -> StoredAction:
        """Persist terminal audit and release or conservatively block the exact target."""
        item, guard = self._transition(action_id, expected_revision)
        if item.phase == "claimed" and state != ActionState.FAILED:
            raise DockSightError("invalid_transition", "Undispatched action can only fail", ErrorKind.CONFLICT)
        item.action.finish(state, message)
        return self._save(
            replace(item, revision=item.revision + 1, phase="terminal"),
            f"action.{state}",
            now,
            _Guard(None, action_id if state == ActionState.INDETERMINATE else guard.blocked, guard.revision + 1),
        )

    async def inspect_block(self, action_id: str) -> BlockedTarget:
        """Read the guard without expiring or modifying unrelated preparations."""
        item = self._entries.get(action_id)
        if item is None:
            raise DockSightError("action_not_found", "Action not found", ErrorKind.NOT_FOUND)
        action = item.action
        guard = self._guards.get((action.host, action.container_id), _Guard())
        return BlockedTarget(
            action_id=action_id,
            host=action.host,
            container_id=action.container_id,
            revision=guard.revision,
            blocked=guard.blocked == action_id,
            unresolved_actions=(guard.blocked,) if guard.blocked else (),
        )

    async def reconcile(
        self, command: ReconcileTarget, observation: ReconciliationObservation, now: datetime
    ) -> BlockedTarget:
        """Audit the confirmed revision and invalidate all exact-target preparations atomically."""
        current = await self.inspect_block(command.action_id)
        validate_reconciliation(current, command, observation)
        if not self._healthy:
            raise StorageError()
        action = self._entries[command.action_id].action
        invalidated: dict[str, StoredAction] = {}
        for identity, stored in self._entries.items():
            if (stored.action.host, stored.action.container_id, stored.action.state) == (
                current.host,
                current.container_id,
                ActionState.PREPARED,
            ):
                item = _detached(stored)
                item.action.invalidate()
                invalidated[identity] = replace(item, revision=item.revision + 1, phase="terminal")
        try:
            self._append_audit(
                "action.reconciled",
                action,
                now,
                {
                    "actor": command.actor,
                    "operator": command.operator,
                    "reason": command.reason,
                    "observation": observation.model_dump(mode="json"),
                },
            )
        except Exception as error:
            self._healthy = False
            raise StorageError() from error
        self._entries.update(invalidated)
        self._guards[(current.host, current.container_id)] = _Guard(revision=current.revision + 1)
        return (await self.inspect_block(command.action_id)).model_copy(update={"observation": observation})


def _available(guard: _Guard) -> None:
    """Reject ambiguous targets before live target reservations."""
    if guard.blocked:
        raise DockSightError(
            "target_indeterminate", "Inspect Docker and reconcile the previous action", ErrorKind.CONFLICT
        )
    if guard.active:
        raise DockSightError("target_busy", "Another action owns this exact target", ErrorKind.CONFLICT)
