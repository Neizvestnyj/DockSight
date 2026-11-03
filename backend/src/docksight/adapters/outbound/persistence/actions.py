import json
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Literal, cast

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from docksight.adapters.outbound.persistence.codec import decode_action, encode_action, utc_text
from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.adapters.outbound.persistence.rows import ActionAuditRow, PreparedActionRow, TargetGuardRow
from docksight.application.action_reconciliation import validate_reconciliation
from docksight.application.investigations.errors import HistoryError
from docksight.application.ports.state import (
    ActionClaim,
    BlockedTarget,
    ReconcileTarget,
    ReconciliationObservation,
    StoredAction,
)
from docksight.domain.actions import ActionState, PreparedAction
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError, ErrorKind


def _conflict() -> DockSightError:
    """Return a safe compare-and-swap failure without exposing stored action metadata."""
    return DockSightError("action_conflict", "Action revision or target ownership changed", ErrorKind.CONFLICT)


def hydrate(row: PreparedActionRow) -> StoredAction:
    """Validate indexed fields against the supported detached domain envelope."""
    action = decode_action(row.snapshot)
    if (action.id, action.actor, action.host, action.container_id, action.idempotency_key) != (
        row.id,
        row.actor,
        row.host,
        row.container_id,
        row.idempotency_key,
    ):
        raise HistoryError("history_unsupported", "Saved action metadata is inconsistent", ErrorKind.CONFLICT)
    phase = row.phase
    if phase not in {"prepared", "claimed", "dispatching", "terminal"}:
        raise HistoryError("history_unsupported", "Saved action phase is unsupported", ErrorKind.CONFLICT)
    _validate_lifecycle(row, action)
    return StoredAction(action, row.revision, cast(Literal["prepared", "claimed", "dispatching", "terminal"], phase))


def _validate_lifecycle(row: PreparedActionRow, action: PreparedAction) -> None:
    """Reject mismatched phases, claims, and dispatch markers before an action can execute."""
    expected = "prepared" if action.state == ActionState.PREPARED else "terminal"
    if action.state == ActionState.RUNNING:
        expected = "dispatching" if row.dispatched_at is not None else "claimed"
    executed = action.state not in {ActionState.PREPARED, ActionState.EXPIRED}
    consistent = (
        row.phase == expected,
        (row.idempotency_key is not None) == executed,
        (row.claimed_at is not None) == executed,
        row.dispatched_at is None or executed,
        action.state not in {ActionState.SUCCEEDED, ActionState.INDETERMINATE} or row.dispatched_at is not None,
    )
    if not all(consistent):
        raise HistoryError("history_unsupported", "Saved action lifecycle is inconsistent", ErrorKind.CONFLICT)


def append_audit(
    session: Session, event: str, action: PreparedAction, now: datetime, extra: JsonObject | None = None
) -> None:
    """Append authoritative safe lifecycle data in the same transaction as state and guards."""
    fields: JsonObject = {
        "host": action.host,
        "container_id": action.container_id,
        "operation": action.operation,
        "state": action.state.value,
        **(extra or {}),
    }
    session.add(
        ActionAuditRow(
            event=event,
            occurred_at=utc_text(now),
            actor=str(fields.pop("actor", action.actor)),
            action_id=action.id,
            fields=json.dumps(fields, separators=(",", ":")),
        )
    )


def save_action(session: Session, stored: StoredAction, now: datetime, event: str) -> StoredAction:
    """Compare-and-swap one revision and append audit before the transaction commits."""
    action = stored.action
    updated = session.scalar(
        update(PreparedActionRow)
        .where(
            PreparedActionRow.id == action.id,
            PreparedActionRow.revision == stored.revision,
        )
        .values(
            revision=stored.revision + 1,
            phase=stored.phase,
            idempotency_key=action.idempotency_key,
            snapshot=encode_action(action),
            **({"claimed_at": utc_text(now)} if stored.phase == "claimed" else {}),
            **({"dispatched_at": utc_text(now)} if stored.phase == "dispatching" else {}),
        )
        .returning(PreparedActionRow.id)
    )
    if updated is None:
        raise _conflict()
    append_audit(session, event, action, now)
    return replace(stored, revision=stored.revision + 1)


def target_guard(session: Session, action: PreparedAction) -> TargetGuardRow:
    """Read or create the unique exact-target reservation inside an adapter transaction."""
    guard = session.get(TargetGuardRow, (action.host, action.container_id))
    if guard is None:
        guard = TargetGuardRow(host=action.host, container_id=action.container_id, revision=0)
        session.add(guard)
        session.flush()
    return guard


def save_guard(session: Session, guard: TargetGuardRow, active: str | None, blocked: str | None) -> None:
    """Compare-and-swap target protection without clearing an unrelated active or blocked action."""
    updated = session.scalar(
        update(TargetGuardRow)
        .where(
            TargetGuardRow.host == guard.host,
            TargetGuardRow.container_id == guard.container_id,
            TargetGuardRow.revision == guard.revision,
        )
        .values(active_action_id=active, blocked_action_id=blocked, revision=guard.revision + 1)
        .returning(TargetGuardRow.host)
    )
    if updated is None:
        raise _conflict()


def _read(session: Session, action_id: str, actor: str | None = None) -> PreparedActionRow:
    """Keep missing and foreign actions indistinguishable at the owned storage boundary."""
    row = session.get(PreparedActionRow, action_id)
    if row is None or (actor is not None and row.actor != actor):
        raise DockSightError("action_not_found", "Action not found", ErrorKind.NOT_FOUND)
    return row


def _expire(session: Session, row: PreparedActionRow, now: datetime) -> StoredAction:
    """Persist expiry before a caller can reject an execution of that preparation."""
    stored = hydrate(row)
    if stored.action.expire(now):
        return save_action(session, replace(stored, phase="terminal"), now, "action.expired")
    return stored


def _transition(session: Session, action_id: str, revision: int) -> tuple[StoredAction, TargetGuardRow]:
    """Require the action revision and its active exact-target reservation together."""
    stored = hydrate(_read(session, action_id))
    guard = target_guard(session, stored.action)
    if stored.revision != revision or guard.active_action_id != action_id:
        raise _conflict()
    return stored, guard


def _inspect(session: Session, action_id: str) -> BlockedTarget:
    """Materialize a blocked target without running expiry or startup recovery."""
    action = hydrate(_read(session, action_id)).action
    guard = session.get(TargetGuardRow, (action.host, action.container_id))
    blocked = guard.blocked_action_id if guard else None
    return BlockedTarget(
        action_id=action_id,
        host=action.host,
        container_id=action.container_id,
        revision=guard.revision if guard else 0,
        blocked=blocked == action_id,
        unresolved_actions=(blocked,) if blocked else (),
    )


class SQLiteActions:
    """Persist domain transitions and authoritative action protection in short isolated transactions."""

    def __init__(self, database: PersistentDatabase, capacity: int = 1000) -> None:
        """Use the lifespan-owned database and bound only live unclaimed preparations."""
        self.database = database
        self.capacity = capacity

    async def add(self, action: PreparedAction, now: datetime) -> StoredAction:
        """Save one validated preparation and audit without deleting execution claims."""
        encoded = encode_action(action)
        action = decode_action(encoded)

        def add(session: Session) -> StoredAction:
            """Check capacity and append a preparation within the serialized write boundary."""
            if session.get(PreparedActionRow, action.id) is not None:
                raise DockSightError("action_conflict", "Action already exists", ErrorKind.CONFLICT)
            _preparation_capacity(session, self.capacity, now)
            session.add(
                PreparedActionRow(
                    id=action.id,
                    actor=action.actor,
                    host=action.host,
                    container_id=action.container_id,
                    phase="prepared",
                    revision=0,
                    snapshot=encoded,
                )
            )
            append_audit(session, "action.prepared", action, now)
            return StoredAction(decode_action(encoded), 0, "prepared")

        return await self.database.transaction(add, write=True)

    async def get(self, action_id: str, actor: str, now: datetime) -> StoredAction:
        """Return an owned detached snapshot after persisting any due preparation expiry."""
        current = await self.database.transaction(lambda session: hydrate(_read(session, action_id, actor)))
        if current.action.state != ActionState.PREPARED or now < current.action.expires_at:
            return current
        return await self.database.transaction(
            lambda session: _expire(session, _read(session, action_id, actor), now), write=True
        )

    async def claim(self, action_id: str, actor: str, key: str, confirmed: bool, now: datetime) -> ActionClaim:
        """Commit claim, key, reservation, and audit together before workflow registration."""

        def claim(session: Session) -> ActionClaim | DockSightError:
            """Commit a due expiry even when domain claim validation rejects execution."""
            stored = _expire(session, _read(session, action_id, actor), now)
            try:
                claimed = stored.action.claim(actor, key, confirmed, now)
            except DockSightError as error:
                return error
            if not claimed:
                return ActionClaim(stored, False)
            guard = target_guard(session, stored.action)
            if guard.blocked_action_id:
                raise DockSightError(
                    "target_indeterminate", "Inspect Docker and reconcile the previous action", ErrorKind.CONFLICT
                )
            if guard.active_action_id:
                raise DockSightError("target_busy", "Another action owns this exact target", ErrorKind.CONFLICT)
            saved = save_action(session, replace(stored, phase="claimed"), now, "action.claimed")
            save_guard(session, guard, action_id, None)
            return ActionClaim(saved, True)

        result = await self.database.transaction(claim, write=True)
        if isinstance(result, DockSightError):
            raise result
        return result

    async def mark_dispatch(self, action_id: str, expected_revision: int, now: datetime) -> StoredAction:
        """Durably record dispatch intent before any Docker command is sent."""

        def dispatch(session: Session) -> StoredAction:
            """Reject repeated dispatch intent and enforce the still-owned target guard."""
            stored, _ = _transition(session, action_id, expected_revision)
            if stored.phase != "claimed":
                raise _conflict()
            return save_action(session, replace(stored, phase="dispatching"), now, "action.dispatching")

        return await self.database.transaction(dispatch, write=True)

    async def complete(
        self, action_id: str, expected_revision: int, state: ActionState, message: str, now: datetime
    ) -> StoredAction:
        """Save a legal outcome, audit, and released or indeterminate guard atomically."""

        def complete(session: Session) -> StoredAction:
            """Keep domain terminal validation authoritative inside the CAS transaction."""
            stored, guard = _transition(session, action_id, expected_revision)
            if stored.phase == "claimed" and state != ActionState.FAILED:
                raise DockSightError("invalid_transition", "Undispatched action can only fail", ErrorKind.CONFLICT)
            stored.action.finish(state, message)
            saved = save_action(session, replace(stored, phase="terminal"), now, f"action.{state}")
            save_guard(
                session, guard, None, action_id if state == ActionState.INDETERMINATE else guard.blocked_action_id
            )
            return saved

        return await self.database.transaction(complete, write=True)

    async def inspect_block(self, action_id: str) -> BlockedTarget:
        """Read only the selected target's persisted unresolved protection."""
        return await self.database.transaction(lambda session: _inspect(session, action_id))

    async def reconcile(
        self, command: ReconcileTarget, observation: ReconciliationObservation, now: datetime
    ) -> BlockedTarget:
        """Clear a confirmed guard and invalidate old preparations in one authoritative audit transaction."""

        def reconcile(session: Session) -> BlockedTarget:
            """Recheck the current guard after the fresh external Docker observation."""
            current = _inspect(session, command.action_id)
            validate_reconciliation(current, command, observation)
            action = hydrate(_read(session, command.action_id)).action
            guard = target_guard(session, action)
            if guard.active_action_id:
                raise _conflict()
            candidates = session.scalars(
                select(PreparedActionRow).where(
                    PreparedActionRow.host == current.host,
                    PreparedActionRow.container_id == current.container_id,
                    PreparedActionRow.phase == "prepared",
                )
            ).all()
            for row in candidates:
                stored = hydrate(row)
                stored.action.invalidate()
                save_action(session, replace(stored, phase="terminal"), now, "action.invalidated")
            append_audit(
                session,
                "action.reconciled",
                action,
                now,
                {
                    "actor": command.actor,
                    "operator": command.operator,
                    "reason": command.reason,
                    "acknowledge_unknown_outcome": True,
                    "observation": observation.model_dump(mode="json"),
                },
            )
            save_guard(session, guard, None, None)
            session.flush()
            return _inspect(session, command.action_id).model_copy(update={"observation": observation})

        return await self.database.transaction(reconcile, write=True)


def _preparation_capacity(session: Session, capacity: int, now: datetime) -> None:
    """Bound live preparations and remove only unclaimed records beyond the retention allowance."""
    live = 0
    for row in session.scalars(select(PreparedActionRow).where(PreparedActionRow.idempotency_key.is_(None))):
        stored = hydrate(row)
        if now >= stored.action.expires_at + timedelta(days=1):
            session.delete(row)
        elif stored.action.state == ActionState.PREPARED and now < stored.action.expires_at:
            live += 1
    if live >= capacity:
        raise DockSightError("action_capacity", "Action capacity reached; retry later", ErrorKind.UNAVAILABLE)
