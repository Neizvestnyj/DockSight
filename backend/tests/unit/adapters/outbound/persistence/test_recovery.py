from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from docksight.adapters.outbound.persistence.actions import SQLiteActions
from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.adapters.outbound.persistence.recovery import recover_actions
from docksight.adapters.outbound.persistence.rows import TargetGuardRow
from docksight.application.investigations.errors import StorageError
from docksight.domain.actions import ActionState, PreparedAction
from docksight.domain.errors import DockSightError

NOW: Final = datetime(2026, 11, 3, tzinfo=UTC)


async def test_recovery_failure_rolls_back_all_actions_before_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from docksight.adapters.outbound.persistence import recovery

    path = tmp_path / "state.sqlite3"
    database = PersistentDatabase(path)
    await database.initialize_server()
    store = SQLiteActions(database)
    identity = str(uuid4())
    await store.add(
        PreparedAction(identity, "alice", "local", "a" * 64, "restart", "fingerprint", NOW + timedelta(minutes=5)), NOW
    )
    await store.claim(identity, "alice", "request-1", True, NOW)
    await database.close()

    def fail_guard(*args: object, **kwargs: object) -> None:
        """Fail after the action update so startup must roll back its audit and terminal result."""
        raise OSError("Guard write failed")

    with monkeypatch.context() as patch:
        patch.setattr(recovery, "save_guard", fail_guard)
        failed = PersistentDatabase(path, recoveries=[recover_actions])
        try:
            with pytest.raises(StorageError):
                await failed.initialize_server()
            assert not failed.healthy
        finally:
            await failed.close()
    recovered = PersistentDatabase(path, recoveries=[recover_actions])
    try:
        report = await recovered.initialize_server()
        assert report.failed_actions == 1
        retained = await SQLiteActions(recovered).claim(identity, "alice", "request-1", True, NOW)
        assert not retained.claimed and retained.stored.action.state == ActionState.FAILED
    finally:
        await recovered.close()


async def test_inconsistent_recovery_guard_refuses_readiness_instead_of_releasing_protection(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    database = PersistentDatabase(path)
    await database.initialize_server()
    store = SQLiteActions(database)
    identity = str(uuid4())
    await store.add(
        PreparedAction(identity, "alice", "local", "a" * 64, "restart", "fingerprint", NOW + timedelta(minutes=5)), NOW
    )
    await store.claim(identity, "alice", "request-1", True, NOW)

    def corrupt(session: Session) -> None:
        """Leave an abandoned claim whose target guard no longer proves exclusive ownership."""
        guard = session.get(TargetGuardRow, ("local", "a" * 64))
        assert guard is not None
        guard.active_action_id = None

    await database.transaction(corrupt, write=True)
    await database.close()
    reopened = PersistentDatabase(path, recoveries=[recover_actions])
    try:
        with pytest.raises(DockSightError) as caught:
            await reopened.initialize_server()
        assert caught.value.code == "recovery_required"
        assert not reopened.healthy
    finally:
        await reopened.close()
