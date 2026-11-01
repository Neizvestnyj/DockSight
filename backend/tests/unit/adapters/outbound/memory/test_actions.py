import asyncio
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from docksight.adapters.outbound.memory.actions import MemoryActions
from docksight.domain.actions import ActionState, PreparedAction
from docksight.domain.errors import DockSightError

_NOW: Final = datetime(2026, 1, 1, tzinfo=UTC)


def prepared(action_id: str, *, actor: str = "alice", expires_at: datetime | None = None) -> PreparedAction:
    """Create a scoped action with a deterministic expiry for store boundary checks."""
    return PreparedAction(
        action_id, actor, "local", "a" * 64, "restart", "snapshot", expires_at or _NOW + timedelta(minutes=5)
    )


async def test_duplicate_id_preserves_the_original_owner() -> None:
    store = MemoryActions(clock=lambda: _NOW)
    await store.add(prepared("existing"))
    with pytest.raises(DockSightError, match="already exists") as caught:
        await store.add(prepared("existing", actor="bob"))
    assert caught.value.code == "action_conflict"
    assert (await store.get("existing", "alice")).actor == "alice"


async def test_capacity_rejects_new_actions_without_discarding_retained_records() -> None:
    store = MemoryActions(capacity=1, clock=lambda: _NOW)
    await store.add(prepared("retained"))
    with pytest.raises(DockSightError) as caught:
        await store.add(prepared("overflow"))
    assert caught.value.code == "action_capacity"
    assert (await store.get("retained", "alice")).id == "retained"
    with pytest.raises(DockSightError) as missing:
        await store.get("overflow", "alice")
    assert missing.value.code == "action_not_found"


async def test_retention_evicts_at_the_boundary_and_not_before_it() -> None:
    now = _NOW
    store = MemoryActions(capacity=1, retention=10, clock=lambda: now)
    await store.add(prepared("old", expires_at=_NOW))
    now += timedelta(seconds=9)
    with pytest.raises(DockSightError) as caught:
        await store.add(prepared("new"))
    assert caught.value.code == "action_capacity"
    now += timedelta(seconds=1)
    await store.add(prepared("new"))
    assert (await store.get("new", "alice")).id == "new"
    with pytest.raises(DockSightError) as missing:
        await store.get("old", "alice")
    assert missing.value.code == "action_not_found"


async def test_running_action_is_not_evicted_after_expiry_and_retention() -> None:
    now = _NOW
    store = MemoryActions(capacity=1, retention=10, clock=lambda: now)
    await store.add(prepared("running", expires_at=_NOW + timedelta(seconds=1)))
    await store.claim("running", "alice", "same-key", True, now)
    now += timedelta(hours=1)
    with pytest.raises(DockSightError) as caught:
        await store.add(prepared("overflow", expires_at=now + timedelta(minutes=5)))
    assert caught.value.code == "action_capacity"
    assert (await store.get("running", "alice")).state == ActionState.RUNNING


@pytest.mark.parametrize(("action_id", "actor"), [("existing", "bob"), ("missing", "alice")])
async def test_missing_and_foreign_actions_are_indistinguishable(action_id: str, actor: str) -> None:
    store = MemoryActions(clock=lambda: _NOW)
    await store.add(prepared("existing"))
    with pytest.raises(DockSightError) as caught:
        await store.get(action_id, actor)
    assert (caught.value.code, caught.value.message) == ("action_not_found", "Action not found")


async def test_foreign_claim_leaves_the_owners_action_prepared() -> None:
    store = MemoryActions(clock=lambda: _NOW)
    await store.add(prepared("owned"))
    with pytest.raises(DockSightError) as caught:
        await store.claim("owned", "bob", "foreign-key", True, _NOW)
    assert caught.value.code == "action_not_found"
    action = await store.get("owned", "alice")
    assert action.state == ActionState.PREPARED
    assert action.idempotency_key is None


async def test_concurrent_duplicate_claims_have_exactly_one_winner() -> None:
    store = MemoryActions(clock=lambda: _NOW)
    await store.add(prepared("owned"))
    results = await asyncio.gather(*(store.claim("owned", "alice", "same-key", True, _NOW) for _ in range(5)))
    assert sum(claimed for _, claimed in results) == 1
    assert all(action.state == ActionState.RUNNING and action.idempotency_key == "same-key" for action, _ in results)


async def test_same_target_waits_for_the_current_holder() -> None:
    store = MemoryActions()
    waiting, entered = asyncio.Event(), asyncio.Event()

    async def acquire() -> None:
        """Signal an attempted acquisition and record actual entry into the target lock."""
        waiting.set()
        async with store.target_lock("local", "container"):
            entered.set()

    async with asyncio.timeout(1):
        async with store.target_lock("local", "container"):
            waiter = asyncio.create_task(acquire())
            await waiting.wait()
            assert not entered.is_set()
        await waiter
    assert entered.is_set()


@pytest.mark.parametrize(("host", "container_id"), [("remote", "container"), ("local", "other")])
async def test_different_targets_do_not_share_a_mutation_lock(host: str, container_id: str) -> None:
    store = MemoryActions()
    async with (
        asyncio.timeout(1),
        store.target_lock("local", "container"),
        store.target_lock(host, container_id),
    ):
        pass


async def test_cancelled_waiter_does_not_release_the_holder_or_block_the_next_waiter() -> None:
    store = MemoryActions()

    async def acquire(waiting: asyncio.Event, entered: asyncio.Event) -> None:
        """Expose acquisition order without replacing the real store lock or using sleeps."""
        waiting.set()
        async with store.target_lock("local", "container"):
            entered.set()

    async with asyncio.timeout(1):
        async with store.target_lock("local", "container"):
            waiting, entered = asyncio.Event(), asyncio.Event()
            cancelled = asyncio.create_task(acquire(waiting, entered))
            await waiting.wait()
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            assert not entered.is_set()
            waiting, entered = asyncio.Event(), asyncio.Event()
            successor = asyncio.create_task(acquire(waiting, entered))
            await waiting.wait()
            assert not entered.is_set()
        await successor
        assert entered.is_set()
        async with store.target_lock("local", "container"):
            pass


async def test_exception_in_the_holder_does_not_poison_future_acquisitions() -> None:
    store = MemoryActions()
    with pytest.raises(ValueError, match="mutation failed"):
        async with store.target_lock("local", "container"):
            raise ValueError("mutation failed")
    async with asyncio.timeout(1), store.target_lock("local", "container"):
        pass


async def test_indeterminate_block_survives_record_cleanup_and_is_scoped_to_its_exact_target() -> None:
    now = _NOW
    store = MemoryActions(capacity=2, retention=0, clock=lambda: now)
    await store.add(prepared("old", expires_at=_NOW))
    await store.block_target("local", "container")
    now += timedelta(seconds=1)
    await store.add(prepared("new"))
    with pytest.raises(DockSightError) as missing:
        await store.get("old", "alice")
    assert missing.value.code == "action_not_found"
    with pytest.raises(DockSightError) as blocked:
        async with store.target_lock("local", "container"):
            pass
    assert blocked.value.code == "target_indeterminate"
    async with store.target_lock("remote", "container"), store.target_lock("local", "other"):
        pass


async def test_retained_indeterminate_blocks_also_bound_store_capacity() -> None:
    store = MemoryActions(capacity=1, clock=lambda: _NOW)
    await store.block_target("local", "container")
    with pytest.raises(DockSightError) as caught:
        await store.add(prepared("new"))
    assert caught.value.code == "action_capacity"
