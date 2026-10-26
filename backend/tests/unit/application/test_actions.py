import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from docksight.adapters.outbound.memory.actions import MemoryActions
from docksight.application.actions import Actions
from docksight.domain.errors import DockSightError
from tests.fakes import FakeAudit, FakeRuntime


async def test_confirmed_action_is_executed_once_for_concurrent_duplicates() -> None:
    runtime, audit = FakeRuntime(), FakeAudit()
    service = Actions(runtime, runtime, MemoryActions(), audit)
    prepared = await service.prepare("alice", "local", runtime.item.id, "restart")
    results = await asyncio.gather(*[service.execute(prepared.id, "alice", "same-key", True) for _ in range(5)])
    assert runtime.mutations == ["restart"]
    assert all(result.state == "succeeded" for result in results)
    assert "action.succeeded" in audit.events


async def test_stale_snapshot_prevents_mutation() -> None:
    runtime = FakeRuntime()
    service = Actions(runtime, runtime, MemoryActions(), FakeAudit())
    prepared = await service.prepare("alice", "local", runtime.item.id, "restart")
    runtime.item = replace(runtime.item, restart_count=9)
    result = await service.execute(prepared.id, "alice", "request-1", True)
    assert result.state == "failed"
    assert not runtime.mutations


async def test_expired_and_unconfirmed_actions_cannot_execute() -> None:
    runtime = FakeRuntime()
    now = datetime.now(UTC)
    service = Actions(runtime, runtime, MemoryActions(), FakeAudit(), clock=lambda: now)
    prepared = await service.prepare("alice", "local", runtime.item.id, "restart")
    with pytest.raises(DockSightError):
        await service.execute(prepared.id, "alice", "request-1", False)
    now += timedelta(minutes=6)
    with pytest.raises(DockSightError):
        await service.execute(prepared.id, "alice", "request-1", True)
    assert not runtime.mutations


async def test_ambiguous_timeout_blocks_new_mutations_for_the_target() -> None:

    class SlowRuntime(FakeRuntime):
        """Delay runtime reads or mutations to exercise timeout handling."""

        async def restart(self, host: str, container_id: str) -> None:
            """Keep a mutation pending beyond the application timeout."""
            await asyncio.sleep(0.05)
            await super().restart(host, container_id)

    runtime = SlowRuntime()
    service = Actions(runtime, runtime, MemoryActions(), FakeAudit(), timeout=0.01)
    prepared = await service.prepare("alice", "local", runtime.item.id, "restart")
    result = await service.execute(prepared.id, "alice", "request-1", True)
    assert result.state == "indeterminate"
    second = await service.prepare("alice", "local", runtime.item.id, "restart")
    result2 = await service.execute(second.id, "alice", "request-2", True)
    assert result2.state == "failed"
    await service.close()
    assert runtime.mutations == ["restart"]


async def test_restart_loop_can_be_stopped() -> None:
    runtime = FakeRuntime()
    runtime.item = replace(runtime.item, state="restarting")
    service = Actions(runtime, runtime, MemoryActions(), FakeAudit())
    prepared = await service.prepare("alice", "local", runtime.item.id, "stop")
    result = await service.execute(prepared.id, "alice", "stop-loop", True)
    assert result.state == "succeeded"
    assert runtime.mutations == ["stop"]


async def test_caller_cancellation_does_not_cancel_started_mutation() -> None:
    started, release = asyncio.Event(), asyncio.Event()

    class WaitingRuntime(FakeRuntime):
        """Keep a mutation pending until the test explicitly releases it."""

        async def restart(self, host: str, container_id: str) -> None:
            """Signal mutation start and wait for the test's completion event."""
            started.set()
            await release.wait()
            await super().restart(host, container_id)

    runtime = WaitingRuntime()
    service = Actions(runtime, runtime, MemoryActions(), FakeAudit())
    prepared = await service.prepare("alice", "local", runtime.item.id, "restart")
    caller = asyncio.create_task(service.execute(prepared.id, "alice", "request-1", True))
    await asyncio.wait_for(started.wait(), 1)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    release.set()
    await service.close()
    result = await service.execute(prepared.id, "alice", "request-1", True)
    assert result.state == "succeeded"
    assert runtime.mutations == ["restart"]


async def test_failed_initial_audit_prevents_mutation() -> None:

    class FailingAudit(FakeAudit):
        """Simulate audit output failure before a runtime mutation starts."""

        async def record(self, event: str, data: dict) -> None:
            """Raise an output failure instead of persisting an audit event."""
            raise OSError("Audit device unavailable")

    runtime = FakeRuntime()
    service = Actions(runtime, runtime, MemoryActions(), FailingAudit())
    prepared = await service.prepare("alice", "local", runtime.item.id, "restart")
    result = await service.execute(prepared.id, "alice", "request-1", True)
    assert result.state == "failed"
    assert not runtime.mutations
