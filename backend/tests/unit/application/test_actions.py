import asyncio
from collections.abc import Coroutine
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import CoroutineType
from typing import Any

import pytest

from docksight.adapters.outbound.memory.actions import MemoryActions
from docksight.application.actions import Actions
from docksight.application.investigations.errors import StorageError
from docksight.application.ports.state import ActionClaim, StoredAction
from docksight.application.views.schemas import ActionView
from docksight.domain.actions import PreparedAction
from docksight.domain.diagnostics import JsonObject
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
    with pytest.raises(DockSightError) as blocked:
        await service.execute(second.id, "alice", "request-2", True)
    assert blocked.value.code == "target_indeterminate"
    await service.close()
    assert runtime.mutations == ["restart"]
    assert (await service.get(prepared.id, "alice")).state == "indeterminate"


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
    result = await service.get(prepared.id, "alice")
    assert result.state == "succeeded"
    assert runtime.mutations == ["restart"]


async def test_failed_mirror_logger_does_not_prevent_durably_audited_mutation() -> None:

    class FailingAudit(FakeAudit):
        """Simulate audit output failure before a runtime mutation starts."""

        async def record(self, event: str, data: JsonObject) -> None:
            """Raise an output failure instead of persisting an audit event."""
            raise OSError("Audit device unavailable")

    runtime = FakeRuntime()
    service = Actions(runtime, runtime, MemoryActions(), FailingAudit())
    prepared = await service.prepare("alice", "local", runtime.item.id, "restart")
    result = await service.execute(prepared.id, "alice", "request-1", True)
    assert result.state == "succeeded"
    assert runtime.mutations == ["restart"]


@pytest.mark.parametrize("event", ["action.claimed", "action.dispatching", "action.succeeded"])
async def test_failed_store_commit_closes_admission_and_never_reports_unsaved_success(event: str) -> None:

    class FailingStore(MemoryActions):
        """Fail authoritative state/audit persistence at one selected execution boundary."""

        def _append_audit(
            self, selected: str, action: PreparedAction, now: datetime, extra: JsonObject | None = None
        ) -> None:
            """Reject the state commit before it publishes a new action or guard."""
            if selected == event:
                raise OSError("State device unavailable")
            super()._append_audit(selected, action, now, extra)

    runtime = FakeRuntime()
    store = FailingStore()
    service = Actions(runtime, runtime, store, FakeAudit())
    prepared = await service.prepare("alice", "local", runtime.item.id, "restart")
    with pytest.raises(StorageError):
        await service.execute(prepared.id, "alice", "request-1", True)
    assert runtime.mutations == (["restart"] if event == "action.succeeded" else [])
    with pytest.raises(StorageError):
        await service.execute(prepared.id, "alice", "request-1", True)
    await service.close()


@pytest.mark.parametrize("shutdown", [False, True])
async def test_cancelled_claim_to_registration_handoff_keeps_a_lifespan_owner(shutdown: bool) -> None:
    committed, release = asyncio.Event(), asyncio.Event()

    class PausedClaim(MemoryActions):
        """Expose a live-process pause after claim commit and before workflow registration."""

        async def claim(self, action_id: str, actor: str, key: str, confirmed: bool, now: datetime) -> ActionClaim:
            """Keep the committed claim awaiting its owning admission task."""
            result = await super().claim(action_id, actor, key, confirmed, now)
            committed.set()
            await release.wait()
            return result

    runtime = FakeRuntime()
    service = Actions(runtime, runtime, PausedClaim(), FakeAudit())
    prepared = await service.prepare("alice", "local", runtime.item.id, "restart")
    caller = asyncio.create_task(service.execute(prepared.id, "alice", "request-1", True))
    await asyncio.wait_for(committed.wait(), 1)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    closing = asyncio.create_task(service.close()) if shutdown else None
    release.set()
    if closing:
        await closing
    else:
        await service.close()
    assert (await service.get(prepared.id, "alice")).state == "succeeded"
    assert runtime.mutations == ["restart"]


async def test_registration_failure_records_failed_before_dispatch_and_releases_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = asyncio.create_task

    def cannot_register(coroutine: Coroutine[Any, Any, ActionView], **kwargs: Any) -> asyncio.Task[ActionView]:
        """Fail only execution-workflow construction while retaining admission ownership."""
        if isinstance(coroutine, CoroutineType) and coroutine.cr_code.co_name == "_run":
            raise RuntimeError("Task registration failed")
        return original(coroutine, **kwargs)

    runtime = FakeRuntime()
    service = Actions(runtime, runtime, MemoryActions(), FakeAudit())
    first = await service.prepare("alice", "local", runtime.item.id, "restart")
    monkeypatch.setattr(asyncio, "create_task", cannot_register)
    with pytest.raises(RuntimeError, match="registration failed"):
        await service.execute(first.id, "alice", "request-1", True)
    assert (await service.get(first.id, "alice")).state == "failed"
    assert not runtime.mutations
    monkeypatch.setattr(asyncio, "create_task", original)
    second = await service.prepare("alice", "local", runtime.item.id, "restart")
    assert (await service.execute(second.id, "alice", "request-2", True)).state == "succeeded"
    await service.close()


async def test_registration_and_failed_terminal_commit_keep_claim_protected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = asyncio.create_task

    def cannot_register(coroutine: Coroutine[Any, Any, ActionView], **kwargs: Any) -> asyncio.Task[ActionView]:
        """Fail workflow creation after admission ownership has already been retained."""
        if isinstance(coroutine, CoroutineType) and coroutine.cr_code.co_name == "_run":
            raise RuntimeError("Task registration failed")
        return original(coroutine, **kwargs)

    class BrokenCompletion(MemoryActions):
        """Reject the authoritative failure record while retaining its claimed target."""

        def _append_audit(
            self, event: str, action: PreparedAction, now: datetime, extra: JsonObject | None = None
        ) -> None:
            """Fail before a terminal action or guard release can be published."""
            if event == "action.failed":
                raise OSError("State unavailable")
            super()._append_audit(event, action, now, extra)

    store = BrokenCompletion()
    runtime = FakeRuntime()
    service = Actions(runtime, runtime, store, FakeAudit())
    action = await service.prepare("alice", "local", runtime.item.id, "restart")
    monkeypatch.setattr(asyncio, "create_task", cannot_register)
    with pytest.raises(StorageError):
        await service.execute(action.id, "alice", "request-1", True)
    assert (await store.get(action.id, "alice", datetime.now(UTC))).phase == "claimed"
    with pytest.raises(StorageError):
        await service.execute(action.id, "alice", "request-1", True)
    assert not runtime.mutations
    await service.close()


async def test_dispatch_marker_settling_after_deadline_does_not_send_docker() -> None:

    class SettlingDispatch(MemoryActions):
        """Reproduce the cancellation-settling contract of an accepted SQLite marker transaction."""

        async def mark_dispatch(self, action_id: str, expected_revision: int, now: datetime) -> StoredAction:
            """Return a committed marker after the workflow timeout cancellation has been consumed."""
            stored = await super().mark_dispatch(action_id, expected_revision, now)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return stored

    runtime = FakeRuntime()
    store = SettlingDispatch()
    service = Actions(runtime, runtime, store, FakeAudit(), timeout=0.01)
    action = await service.prepare("alice", "local", runtime.item.id, "restart")
    result = await service.execute(action.id, "alice", "request-1", True)
    assert result.state == "indeterminate"
    assert not runtime.mutations
    assert (await store.inspect_block(action.id)).blocked
    await service.close()
