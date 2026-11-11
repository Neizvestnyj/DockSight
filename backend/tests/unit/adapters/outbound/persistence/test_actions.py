import asyncio
import threading
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
from docksight.adapters.outbound.persistence.rows import ActionAuditRow, PreparedActionRow
from docksight.application.investigations.errors import HistoryError
from docksight.domain.actions import ActionState, PreparedAction
from docksight.domain.errors import DockSightError

NOW: Final = datetime(2026, 11, 3, tzinfo=UTC)


def prepared() -> PreparedAction:
    """Create an ordinary unclaimed action whose protection must survive adapter reopening."""
    return PreparedAction(
        str(uuid4()), "alice", "local", "a" * 64, "restart", "fingerprint", NOW + timedelta(minutes=5)
    )


@pytest.mark.parametrize("corruption", ["version", "phase", "identity", "claim_timestamp"])
async def test_corrupt_or_unsupported_actions_never_enter_execution(tmp_path: Path, corruption: str) -> None:
    database = PersistentDatabase(tmp_path / "state.sqlite3")
    await database.initialize_server()
    store = SQLiteActions(database)
    action = prepared()
    try:
        await store.add(action, NOW)

        def corrupt(session: Session) -> None:
            """Simulate incompatible or damaged durable metadata without changing another target."""
            row = session.get(PreparedActionRow, action.id)
            assert row is not None
            if corruption == "version":
                row.snapshot = row.snapshot.replace('"schema_version":1', '"schema_version":99')
            elif corruption == "phase":
                row.phase = "terminal"
            elif corruption == "identity":
                row.host = "different"
            else:
                row.claimed_at = NOW.isoformat()

        await database.transaction(corrupt, write=True)
        with pytest.raises(HistoryError) as caught:
            await store.claim(action.id, "alice", "request-1", True, NOW)
        assert caught.value.code == "history_unsupported"
    finally:
        await database.close()


async def test_sqlite_capacity_counts_preparations_without_deleting_execution_audit(tmp_path: Path) -> None:
    database = PersistentDatabase(tmp_path / "state.sqlite3")
    await database.initialize_server()
    store = SQLiteActions(database, capacity=1)
    action = prepared()
    try:
        await store.add(action, NOW)
        with pytest.raises(DockSightError) as caught:
            await store.add(prepared(), NOW)
        assert caught.value.code == "action_capacity"
        claimed = await store.claim(action.id, "alice", "request-1", True, NOW)
        await store.complete(action.id, claimed.stored.revision, ActionState.FAILED, "Not dispatched", NOW)
        unclaimed = prepared()
        await store.add(unclaimed, NOW)
        await store.add(prepared(), NOW + timedelta(days=2))
        assert (await store.claim(action.id, "alice", "request-1", True, NOW + timedelta(days=2))).claimed is False
        with pytest.raises(DockSightError):
            await store.get(unclaimed.id, "alice", NOW)
        events = await database.transaction(
            lambda session: list(
                session.scalars(select(ActionAuditRow.event).where(ActionAuditRow.action_id == action.id))
            )
        )
        assert events == ["action.prepared", "action.claimed", "action.failed"]
    finally:
        await database.close()


async def test_queued_add_detaches_input_before_the_database_worker_runs(tmp_path: Path) -> None:
    database = PersistentDatabase(tmp_path / "state.sqlite3")
    await database.initialize_server()
    entered, release = threading.Event(), threading.Event()

    def barrier(session: Session) -> None:
        """Hold only a test transaction to expose mutation of the caller-owned input."""
        entered.set()
        assert release.wait(5)

    blocked = asyncio.create_task(database.transaction(barrier))
    await asyncio.to_thread(entered.wait, 5)
    action = prepared()
    store = SQLiteActions(database)
    adding = asyncio.create_task(store.add(action, NOW))
    try:
        await asyncio.sleep(0)
        action.host = "unsaved-host"
        release.set()
        await blocked
        await adding
        assert (await store.get(action.id, "alice", NOW)).action.host == "local"
    finally:
        release.set()
        await asyncio.gather(blocked, adding, return_exceptions=True)
        await database.close()


@pytest.mark.parametrize("persistent", [False, True], ids=["memory", "sqlite"])
async def test_read_of_other_preparation_reports_exact_target_block_without_foreign_action_id(
    tmp_path: Path, persistent: bool
) -> None:
    database = PersistentDatabase(tmp_path / "state.sqlite3")
    await database.initialize_server()
    store = SQLiteActions(database) if persistent else MemoryActions()
    first, second = prepared(), prepared()
    second.actor = "bob"
    try:
        await store.add(first, NOW)
        await store.add(second, NOW)
        claimed = await store.claim(first.id, "alice", "key-one", True, NOW)
        dispatched = await store.mark_dispatch(first.id, claimed.stored.revision, NOW)
        await store.complete(first.id, dispatched.revision, ActionState.INDETERMINATE, "Unknown", NOW)
        with pytest.raises(DockSightError) as caught:
            await store.get(second.id, "bob", NOW)
        assert caught.value.code == "target_indeterminate"
        assert first.id not in caught.value.message
        assert (await store.get(first.id, "alice", NOW)).action.state == ActionState.INDETERMINATE
        assert not (await store.claim(first.id, "alice", "key-one", True, NOW)).claimed
        with pytest.raises(DockSightError) as foreign:
            await store.get(second.id, "alice", NOW)
        assert foreign.value.code == "action_not_found"
    finally:
        await database.close()
