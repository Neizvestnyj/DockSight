from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from uuid import uuid4

import pytest

from docksight.adapters.outbound.memory.actions import MemoryActions
from docksight.adapters.outbound.persistence.actions import SQLiteActions
from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.application.action_reconciliation import ActionReconciliation
from docksight.application.investigations.errors import StorageError
from docksight.application.ports.state import ActionStore, ReconcileTarget
from docksight.domain.actions import ActionState, PreparedAction
from docksight.domain.errors import DockSightError, ErrorKind
from docksight.domain.runtime import ContainerSnapshot
from tests.fakes import FakeRuntime

NOW: Final = datetime(2026, 11, 3, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
async def reconciliation_store(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[ActionStore]:
    """Compare offline reconciliation against both explicit action-store implementations."""
    if request.param == "memory":
        yield MemoryActions()
        return
    database = PersistentDatabase(tmp_path / "reconciliation.sqlite3")
    await database.initialize_server()
    try:
        yield SQLiteActions(database)
    finally:
        await database.close()


async def blocked_actions(store: ActionStore, runtime: FakeRuntime) -> tuple[str, str]:
    """Seed one unknown outcome and a distinct stale preparation for the same exact target."""
    identities = str(uuid4()), str(uuid4())
    for identity in identities:
        await store.add(
            PreparedAction(
                identity,
                "alice",
                "local",
                runtime.item.id,
                "restart",
                runtime.item.fingerprint,
                NOW + timedelta(minutes=5),
            ),
            NOW,
        )
    claim = await store.claim(identities[0], "alice", "request-1", True, NOW)
    dispatch = await store.mark_dispatch(identities[0], claim.stored.revision, NOW)
    await store.complete(identities[0], dispatch.revision, ActionState.INDETERMINATE, "Unknown", NOW)
    return identities


async def confirmation(store: ActionStore, identity: str, **changes: object) -> ReconcileTarget:
    """Build an explicit operator confirmation using the actual inspected guard revision."""
    guard = await store.inspect_block(identity)
    return ReconcileTarget.model_validate(
        {
            "action_id": identity,
            "expected_revision": guard.revision,
            "confirm_target": f"local/{'a' * 64}",
            "actor": "alice",
            "operator": "host-operator",
            "reason": "Verified the old process and Docker command have settled",
            "acknowledge_unknown_outcome": True,
            **changes,
        }
    )


async def test_explicit_reconciliation_keeps_unknown_outcome_and_invalidates_old_preparations(
    reconciliation_store: ActionStore,
) -> None:
    runtime = FakeRuntime()
    old, stale = await blocked_actions(reconciliation_store, runtime)
    service = ActionReconciliation(runtime, reconciliation_store, ["alice"], clock=lambda: NOW)
    preview = await service.inspect(old)
    assert preview.blocked and preview.unresolved_actions == (old,)
    assert preview.observation is not None and preview.observation.observed_at == NOW
    result = await service.reconcile(await confirmation(reconciliation_store, old))
    assert not result.blocked and result.revision == preview.revision + 1
    assert (await reconciliation_store.get(old, "alice", NOW)).action.state == ActionState.INDETERMINATE
    assert (await reconciliation_store.get(stale, "alice", NOW)).action.state == ActionState.EXPIRED
    with pytest.raises(DockSightError):
        await reconciliation_store.claim(stale, "alice", "new-key", True, NOW)
    assert not runtime.mutations


@pytest.mark.parametrize(
    "changes",
    [
        {"acknowledge_unknown_outcome": False},
        {"expected_revision": 0},
        {"confirm_target": f"other/{'a' * 64}"},
        {"actor": "unconfigured"},
        {"reason": "   "},
    ],
)
async def test_incomplete_or_stale_confirmation_keeps_target_blocked(
    reconciliation_store: ActionStore,
    changes: dict[str, object],
) -> None:
    runtime = FakeRuntime()
    old, stale = await blocked_actions(reconciliation_store, runtime)
    before = await reconciliation_store.inspect_block(old)
    service = ActionReconciliation(runtime, reconciliation_store, ["alice"], clock=lambda: NOW)
    with pytest.raises(DockSightError):
        await service.reconcile(await confirmation(reconciliation_store, old, **changes))
    assert await reconciliation_store.inspect_block(old) == before
    with pytest.raises(DockSightError) as unavailable:
        await reconciliation_store.get(stale, "alice", NOW)
    assert unavailable.value.code == "target_indeterminate"
    assert not runtime.mutations


@pytest.mark.parametrize("removed", [False, True])
async def test_unavailable_docker_cannot_unblock_but_verified_removal_can(
    reconciliation_store: ActionStore,
    removed: bool,
) -> None:

    class MissingRuntime(FakeRuntime):
        """Distinguish a verified missing exact resource from unavailable Docker access."""

        async def inspect(self, host: str, container_id: str) -> ContainerSnapshot:
            """Return the same typed errors as the configured Docker reader."""
            raise DockSightError(
                "container_not_found" if removed else "runtime_unavailable", "Not available", ErrorKind.UNAVAILABLE
            )

    runtime = MissingRuntime()
    old, _ = await blocked_actions(reconciliation_store, runtime)
    service = ActionReconciliation(runtime, reconciliation_store, ["alice"], clock=lambda: NOW)
    command = await confirmation(reconciliation_store, old)
    if removed:
        result = await service.reconcile(command)
        assert not result.blocked and result.observation is not None and not result.observation.exists
    else:
        with pytest.raises(DockSightError):
            await service.reconcile(command)
        assert (await reconciliation_store.inspect_block(old)).blocked
    assert not runtime.mutations


async def test_failed_reconciliation_audit_keeps_block_and_preparations(
    reconciliation_store: ActionStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from docksight.adapters.outbound.persistence import actions as persistence

    runtime = FakeRuntime()
    old, stale = await blocked_actions(reconciliation_store, runtime)
    before = await reconciliation_store.inspect_block(old)
    command = await confirmation(reconciliation_store, old)

    def cannot_audit(*args: object, **kwargs: object) -> None:
        """Reject authoritative audit appends so the transaction must preserve every guard."""
        raise OSError("Audit storage unavailable")

    if isinstance(reconciliation_store, MemoryActions):
        monkeypatch.setattr(reconciliation_store, "_append_audit", cannot_audit)
    else:
        monkeypatch.setattr(persistence, "append_audit", cannot_audit)
    service = ActionReconciliation(runtime, reconciliation_store, ["alice"], clock=lambda: NOW)
    with pytest.raises(StorageError):
        await service.reconcile(command)
    assert await reconciliation_store.inspect_block(old) == before
    with pytest.raises(DockSightError) as unavailable:
        await reconciliation_store.get(stale, "alice", NOW)
    assert unavailable.value.code == "target_indeterminate"
    assert (await reconciliation_store.get(old, "alice", NOW)).action.state == ActionState.INDETERMINATE
    assert not runtime.mutations
