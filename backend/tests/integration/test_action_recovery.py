import asyncio
import os
import sys
import threading
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from docksight.adapters.outbound.memory.actions import MemoryActions
from docksight.adapters.outbound.persistence.actions import SQLiteActions
from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.adapters.outbound.persistence.recovery import recover_actions
from docksight.adapters.outbound.persistence.rows import ActionAuditRow
from docksight.application.actions import Actions
from docksight.application.investigations.errors import StorageError
from docksight.application.ports.state import ActionClaim, ActionOrigin, ActionStore
from docksight.domain.actions import ActionState, PreparedAction
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError
from tests.fakes import FakeAudit, FakeRuntime

NOW: Final = datetime(2026, 11, 3, tzinfo=UTC)
WORKER_PATH: Final = str(Path(__file__).resolve())


def prepared(identity: str | None = None, *, container_id: str = "a" * 64) -> PreparedAction:
    """Create a fresh exact-target action for the common detached-store contract."""
    return PreparedAction(
        identity or str(uuid4()), "alice", "local", container_id, "restart", "fingerprint", NOW + timedelta(minutes=5)
    )


@pytest.fixture(params=["memory", "sqlite"])
async def action_store(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[ActionStore]:
    """Run the explicit transition contract against both real action adapters."""
    if request.param == "memory":
        yield MemoryActions()
        return
    database = PersistentDatabase(tmp_path / "actions.sqlite3", recoveries=[recover_actions])
    await database.initialize_server()
    try:
        yield SQLiteActions(database)
    finally:
        await database.close()


async def test_detached_claim_needs_explicit_dispatch_and_completion(action_store: ActionStore) -> None:
    action = prepared()
    added = await action_store.add(action, NOW)
    action.message = "Unsaved edit"
    assert (await action_store.get(action.id, "alice", NOW)).action.message == "Confirmation required"
    claim = await action_store.claim(action.id, "alice", "request-1", True, NOW)
    assert claim.claimed and claim.stored.revision == added.revision + 1
    claim.stored.action.finish(ActionState.SUCCEEDED, "Unsaved completion")
    retained = await action_store.get(action.id, "alice", NOW)
    assert retained.action.state == ActionState.RUNNING and retained.phase == "claimed"
    dispatched = await action_store.mark_dispatch(action.id, retained.revision, NOW)
    saved = await action_store.complete(action.id, dispatched.revision, ActionState.SUCCEEDED, "Done", NOW)
    assert saved.action.state == ActionState.SUCCEEDED and saved.phase == "terminal"
    assert (await action_store.get(action.id, "alice", NOW)).action.message == "Done"
    with pytest.raises(DockSightError):
        await action_store.complete(action.id, dispatched.revision, ActionState.FAILED, "Late", NOW)


async def test_expiry_commits_despite_rejected_claim(action_store: ActionStore) -> None:
    action = prepared()
    await action_store.add(action, NOW)
    with pytest.raises(DockSightError) as caught:
        await action_store.claim(action.id, "alice", "request-1", True, action.expires_at)
    assert caught.value.code == "action_expired"
    saved = await action_store.get(action.id, "alice", NOW)
    assert saved.action.state == ActionState.EXPIRED and saved.phase == "terminal"
    assert saved.revision == 1


async def test_target_reservation_and_blocks_are_atomic(action_store: ActionStore) -> None:
    first, second, other = prepared(), prepared(), prepared(container_id="b" * 64)
    for action in (first, second, other):
        await action_store.add(action, NOW)
    claimed = await action_store.claim(first.id, "alice", "request-1", True, NOW)
    with pytest.raises(DockSightError) as busy:
        await action_store.claim(second.id, "alice", "request-2", True, NOW)
    assert busy.value.code == "target_busy"
    assert (await action_store.get(second.id, "alice", NOW)).action.idempotency_key is None
    assert (await action_store.claim(other.id, "alice", "request-3", True, NOW)).claimed
    dispatch = await action_store.mark_dispatch(first.id, claimed.stored.revision, NOW)
    await action_store.complete(first.id, dispatch.revision, ActionState.INDETERMINATE, "Unknown", NOW)
    with pytest.raises(DockSightError) as blocked:
        await action_store.claim(second.id, "alice", "request-2", True, NOW)
    assert blocked.value.code == "target_indeterminate"
    duplicate = await action_store.claim(first.id, "alice", "request-1", True, NOW + timedelta(days=1))
    assert not duplicate.claimed and duplicate.stored.action.state == ActionState.INDETERMINATE
    with pytest.raises(DockSightError) as conflict:
        await action_store.claim(first.id, "alice", "different", True, NOW)
    assert conflict.value.code == "action_conflict"


async def test_owner_and_compare_and_swap_rejections_preserve_state(action_store: ActionStore) -> None:
    action = prepared()
    await action_store.add(action, NOW)
    for identity, actor in [(action.id, "bob"), ("missing", "alice")]:
        with pytest.raises(DockSightError) as caught:
            await action_store.claim(identity, actor, "request-1", True, NOW)
        assert caught.value.code == "action_not_found"
    claim = await action_store.claim(action.id, "alice", "request-1", True, NOW)
    with pytest.raises(DockSightError):
        await action_store.mark_dispatch(action.id, claim.stored.revision - 1, NOW)
    assert (await action_store.get(action.id, "alice", NOW)).phase == "claimed"


async def test_two_concurrent_action_claims_cannot_dispatch_the_same_target(action_store: ActionStore) -> None:
    first, second = prepared(), prepared()
    await action_store.add(first, NOW)
    await action_store.add(second, NOW)
    results = await asyncio.gather(
        action_store.claim(first.id, "alice", "request-1", True, NOW),
        action_store.claim(second.id, "alice", "request-2", True, NOW),
        return_exceptions=True,
    )
    rejected = [value for value in results if isinstance(value, DockSightError)]
    assert len(rejected) == 1 and rejected[0].code == "target_busy"
    phases = [(await action_store.get(value.id, "alice", NOW)).phase for value in (first, second)]
    assert sorted(phases) == ["claimed", "prepared"]


@pytest.mark.parametrize(
    ("event", "phase", "sent"),
    [
        ("action.claimed", "prepared", 0),
        ("action.dispatching", "claimed", 0),
        ("action.succeeded", "dispatching", 1),
    ],
)
async def test_sqlite_audit_commit_failure_preserves_guard_and_stops_mutation_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event: str,
    phase: str,
    sent: int,
) -> None:
    from docksight.adapters.outbound.persistence import actions as persistence

    database = PersistentDatabase(tmp_path / "state.sqlite3", recoveries=[recover_actions])
    await database.initialize_server()
    store = SQLiteActions(database)
    runtime = FakeRuntime()
    service = Actions(runtime, runtime, store, FakeAudit())
    original = persistence.append_audit

    def failing_audit(
        session: Session, selected: str, action: PreparedAction, now: datetime, extra: JsonObject | None = None
    ) -> None:
        """Fail the authoritative audit append after state SQL but before transaction commit."""
        if selected == event:
            raise OSError("Disk unavailable")
        original(session, selected, action, now, extra)

    try:
        action = await service.prepare("alice", "local", runtime.item.id, "restart")
        monkeypatch.setattr(persistence, "append_audit", failing_audit)
        with pytest.raises(StorageError):
            await service.execute(action.id, "alice", "request-1", True)
        assert len(runtime.mutations) == sent
        assert not database.healthy
        assert (await store.get(action.id, "alice", NOW)).phase == phase
        with pytest.raises(StorageError):
            await service.execute(action.id, "alice", "request-1", True)
    finally:
        await service.close()
        await database.close()


@pytest.mark.parametrize("shutdown", [False, True])
async def test_sqlite_claim_commit_handoff_survives_cancelled_observer_and_shutdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shutdown: bool,
) -> None:
    database = PersistentDatabase(tmp_path / "state.sqlite3", recoveries=[recover_actions])
    await database.initialize_server()
    store = SQLiteActions(database)
    runtime = FakeRuntime()
    service = Actions(runtime, runtime, store, FakeAudit())
    committed, release = asyncio.Event(), asyncio.Event()
    original = store.claim

    async def paused_claim(action_id: str, actor: str, key: str, confirmed: bool, now: datetime) -> ActionClaim:
        """Pause after a real SQLite claim commit while its retained admission owns registration."""
        result = await original(action_id, actor, key, confirmed, now)
        committed.set()
        await release.wait()
        return result

    monkeypatch.setattr(store, "claim", paused_claim)
    caller = None
    try:
        action = await service.prepare("alice", "local", runtime.item.id, "restart")
        caller = asyncio.create_task(service.execute(action.id, "alice", "request-1", True))
        await asyncio.wait_for(committed.wait(), 2)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        closing = asyncio.create_task(service.close()) if shutdown else None
        if closing:
            await asyncio.sleep(0)
            assert not closing.done()
        release.set()
        await (closing if closing else service.close())
        assert (await service.get(action.id, "alice")).state == "succeeded"
        assert runtime.mutations == ["restart"]
    finally:
        release.set()
        if caller is not None:
            await asyncio.gather(caller, return_exceptions=True)
        await service.close()
        await database.close()


async def test_real_sqlite_dispatch_commit_settles_timeout_without_sending_late_docker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from docksight.adapters.outbound.persistence import actions as persistence

    database = PersistentDatabase(tmp_path / "state.sqlite3", recoveries=[recover_actions])
    await database.initialize_server()
    store = SQLiteActions(database)
    runtime = FakeRuntime()
    service = Actions(runtime, runtime, store, FakeAudit(), timeout=0.02)
    entered, release = threading.Event(), threading.Event()
    original = persistence.append_audit

    def paused_audit(
        session: Session,
        event: str,
        action: PreparedAction,
        now: datetime,
        extra: JsonObject | None = None,
        origin: ActionOrigin | None = None,
    ) -> None:
        """Hold the accepted marker write until its awaiting workflow deadline has elapsed."""
        original(session, event, action, now, extra, origin)
        if event == "action.dispatching":
            entered.set()
            assert release.wait(5)

    monkeypatch.setattr(persistence, "append_audit", paused_audit)
    caller = None
    try:
        action = await service.prepare("alice", "local", runtime.item.id, "restart")
        caller = asyncio.create_task(service.execute(action.id, "alice", "request-1", True))
        assert await asyncio.to_thread(entered.wait, 2)
        await asyncio.sleep(0.05)
        release.set()
        assert (await caller).state == "indeterminate"
        assert not runtime.mutations
        assert (await store.inspect_block(action.id)).blocked
    finally:
        release.set()
        if caller is not None:
            await asyncio.gather(caller, return_exceptions=True)
        await service.close()
        await database.close()


@pytest.mark.parametrize(
    ("barrier", "expected_state", "dispatches", "blocked"),
    [
        ("claim", "failed", 0, False),
        ("dispatch", "indeterminate", 0, True),
        ("docker", "indeterminate", 1, True),
        ("complete", "succeeded", 1, False),
    ],
)
async def test_process_death_retains_outcome_keys_audit_and_target_guard(
    tmp_path: Path, barrier: str, expected_state: str, dispatches: int, blocked: bool
) -> None:
    state, sent = tmp_path / "state.sqlite3", tmp_path / "dispatches.txt"
    identity = str(uuid4())
    backend = Path(__file__).parents[2]
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join((str(backend / "src"), str(backend)))}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        WORKER_PATH,
        str(state),
        str(sent),
        identity,
        barrier,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    assert process.stdout is not None
    try:
        async with asyncio.timeout(20):
            line = await process.stdout.readline()
        if line.strip() != b"READY":
            if process.returncode is None:
                process.kill()
            _, errors = await process.communicate()
            pytest.fail(f"Crash worker failed: {line!r} {errors.decode()}")
    finally:
        if process.returncode is None:
            process.kill()
        await process.communicate()
    assert await asyncio.to_thread(lambda: sent.read_text().count("restart") if sent.exists() else 0) == dispatches
    await verify_restarts(state, identity, expected_state, blocked)


async def verify_restarts(state: Path, identity: str, expected_state: str, blocked: bool) -> None:
    """Assert original keys, audit, and exact-target protection across two independent startups."""
    for restart in range(2):
        database = PersistentDatabase(state, recoveries=[recover_actions])
        try:
            report = await database.initialize_server()
            store = SQLiteActions(database)
            retained = await store.claim(identity, "alice", "request-1", True, NOW)
            assert not retained.claimed and retained.stored.action.state == expected_state
            with pytest.raises(DockSightError):
                await store.claim(identity, "alice", "new-key", True, NOW)
            candidate = prepared()
            await store.add(candidate, NOW)
            if blocked:
                with pytest.raises(DockSightError) as caught:
                    await store.claim(candidate.id, "alice", "another-key", True, NOW)
                assert caught.value.code == "target_indeterminate"
            else:
                claimed = await store.claim(candidate.id, "alice", "another-key", True, NOW)
                await store.complete(candidate.id, claimed.stored.revision, ActionState.FAILED, "Not sent", NOW)
            events = await database.transaction(
                lambda session: list(
                    session.scalars(select(ActionAuditRow.event).where(ActionAuditRow.action_id == identity))
                )
            )
            assert "action.prepared" in events and "action.claimed" in events
            assert f"action.{expected_state}" in events
            if restart:
                assert report.failed_actions == report.indeterminate_actions == 0
        finally:
            await database.close()


async def crash_worker(path: Path, sent: Path, identity: str, barrier: str) -> None:
    """Stop at a committed lifecycle boundary for an actual parent-triggered process death."""
    database = PersistentDatabase(path, recoveries=[recover_actions])
    await database.initialize_server()
    store = SQLiteActions(database)
    await store.add(prepared(identity), NOW)
    claimed = await store.claim(identity, "alice", "request-1", True, NOW)
    if barrier != "claim":
        dispatch = await store.mark_dispatch(identity, claimed.stored.revision, NOW)
        if barrier != "dispatch":
            await asyncio.to_thread(sent.write_text, "restart\n")
            if barrier == "complete":
                await store.complete(identity, dispatch.revision, ActionState.SUCCEEDED, "Done", NOW)
    print("READY", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(crash_worker(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]))
