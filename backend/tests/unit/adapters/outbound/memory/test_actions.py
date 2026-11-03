from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from docksight.adapters.outbound.memory.actions import MemoryActions
from docksight.domain.actions import ActionState, PreparedAction
from docksight.domain.errors import DockSightError

NOW: Final = datetime(2026, 1, 1, tzinfo=UTC)


def prepared(identity: str, *, expires_at: datetime | None = None, actor: str = "alice") -> PreparedAction:
    """Create a fresh domain preparation for memory retention and capacity behavior."""
    return PreparedAction(
        identity, actor, "local", "a" * 64, "restart", "snapshot", expires_at or NOW + timedelta(minutes=5)
    )


async def test_duplicate_id_preserves_original_owner() -> None:
    store = MemoryActions()
    await store.add(prepared("existing"), NOW)
    with pytest.raises(DockSightError):
        await store.add(prepared("existing", actor="bob"), NOW)
    assert (await store.get("existing", "alice", NOW)).action.actor == "alice"


async def test_capacity_counts_live_preparations_and_never_evicts_claimed_outcomes() -> None:
    store = MemoryActions(capacity=1)
    await store.add(prepared("retained"), NOW)
    with pytest.raises(DockSightError) as caught:
        await store.add(prepared("overflow"), NOW)
    assert caught.value.code == "action_capacity"
    claim = await store.claim("retained", "alice", "request-1", True, NOW)
    await store.complete("retained", claim.stored.revision, ActionState.FAILED, "Not sent", NOW)
    await store.add(prepared("new"), NOW)
    assert (await store.claim("retained", "alice", "request-1", True, NOW + timedelta(days=30))).claimed is False
    assert (await store.get("retained", "alice", NOW)).action.state == ActionState.FAILED


async def test_unclaimed_retention_does_not_discard_a_block_or_idempotency_key() -> None:
    store = MemoryActions(capacity=2, retention=10)
    await store.add(prepared("unknown"), NOW)
    claimed = await store.claim("unknown", "alice", "request-1", True, NOW)
    dispatch = await store.mark_dispatch("unknown", claimed.stored.revision, NOW)
    await store.complete("unknown", dispatch.revision, ActionState.INDETERMINATE, "Unknown", NOW)
    await store.add(prepared("expired", expires_at=NOW), NOW)
    await store.add(prepared("new", expires_at=NOW + timedelta(days=3)), NOW + timedelta(days=2))
    with pytest.raises(DockSightError):
        await store.get("expired", "alice", NOW)
    assert (await store.inspect_block("unknown")).blocked
    assert (await store.claim("unknown", "alice", "request-1", True, NOW + timedelta(days=2))).claimed is False
