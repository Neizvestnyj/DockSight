import asyncio
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from docksight.adapters.outbound.persistence.database import HEAD, PersistentDatabase, RecoveryReport
from docksight.adapters.outbound.persistence.investigations import SQLiteInvestigations
from docksight.adapters.outbound.persistence.maintenance import StateMaintenance
from docksight.adapters.outbound.persistence.rows import ActionAuditRow, PreparedActionRow, TargetGuardRow
from docksight.application.investigations.errors import StorageError


async def test_other_process_cannot_acquire_canonical_state_path(tmp_path: Path) -> None:
    database = PersistentDatabase(tmp_path / "state.sqlite3")
    await database.initialize_server()
    source = (
        "import asyncio,sys\n"
        "from pathlib import Path\n"
        "from docksight.adapters.outbound.persistence.database import PersistentDatabase\n"
        "from docksight.application.investigations.errors import StorageError\n"
        "async def main():\n"
        "    db=PersistentDatabase(Path(sys.argv[1]))\n"
        "    try:\n"
        "        await db.initialize_server()\n"
        "    except StorageError as error:\n"
        "        print(error.code)\n"
        "    finally:\n"
        "        await db.close()\n"
        "asyncio.run(main())\n"
    )
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c", source, str(tmp_path / "nested" / ".." / "state.sqlite3")],
            capture_output=True,
            text=True,
            timeout=15,
            env=os.environ.copy(),
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "storage_locked"
    finally:
        await database.close()


async def test_failed_migration_preserves_existing_data_and_rolls_back_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.sqlite3"
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.execute("CREATE TABLE legacy (value TEXT)")
        connection.execute("INSERT INTO legacy VALUES ('keep')")

    def fail(config: Config, revision: str) -> None:
        """Fail after a real transactional DDL write to exercise SQLite rollback semantics."""
        connection = config.attributes["connection"]
        assert isinstance(connection, Connection)
        connection.exec_driver_sql("CREATE TABLE partial_upgrade (value TEXT)")
        raise OSError("migration stopped")

    monkeypatch.setattr("docksight.adapters.outbound.persistence.database.command.upgrade", fail)
    database = PersistentDatabase(path)
    try:
        with pytest.raises(StorageError):
            await database.initialize_server()
        assert not database.healthy
    finally:
        await database.close()
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        assert connection.execute("SELECT value FROM legacy").fetchone() == ("keep",)
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='partial_upgrade'").fetchone() is None


async def test_newer_schema_refuses_server_and_reconcile_writes(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('9999_future')")
    before = path.read_bytes()
    for mode in (None, "reconcile", "migrate"):
        database = PersistentDatabase(path)
        try:
            with pytest.raises(StorageError) as caught:
                if mode is None:
                    await database.initialize_server()
                else:
                    await database.open_existing(mode)
            assert caught.value.code == "storage_schema_unsupported"
            assert not database.healthy
        finally:
            await database.close()
    assert path.read_bytes() == before


@pytest.mark.parametrize("failure", ["corrupt", "unwritable"])
async def test_unusable_database_never_chooses_memory(tmp_path: Path, failure: str) -> None:
    path = tmp_path / "state.sqlite3"
    if failure == "corrupt":
        path.write_bytes(b"not a database")
    else:
        parent = tmp_path / "not-a-directory"
        parent.write_text("occupied", encoding="utf-8")
        path = parent / "state.sqlite3"
    database = PersistentDatabase(path)
    try:
        with pytest.raises(StorageError):
            await database.initialize_server()
        assert not database.healthy
    finally:
        await database.close()


def old_state(path: Path) -> None:
    """Build an older offline state with abandoned work and audit that maintenance must preserve."""
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('0000_older')")
        connection.execute("CREATE TABLE turns (state TEXT)")
        connection.execute("INSERT INTO turns VALUES ('running')")
        connection.execute("CREATE TABLE prepared_actions (phase TEXT)")
        connection.execute("INSERT INTO prepared_actions VALUES ('dispatching')")
        connection.execute("CREATE TABLE action_audit (event TEXT)")
        connection.execute("INSERT INTO action_audit VALUES ('action.claimed')")


async def test_status_and_backup_preserve_old_lifecycle_and_schema(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    old_state(path)
    before = path.read_bytes()
    status_owner = PersistentDatabase(path)
    await status_owner.open_existing("status")
    try:
        status = await StateMaintenance(status_owner).status()
        assert status.schema_revision == "0000_older"
        assert status.recovery_required
    finally:
        await status_owner.close()
    backup_owner = PersistentDatabase(path)
    await backup_owner.open_existing("backup")
    try:
        copied = await StateMaintenance(backup_owner).backup(tmp_path / "backup.sqlite3")
        assert copied[0].read_bytes() == before
    finally:
        await backup_owner.close()
    assert path.read_bytes() == before


async def test_backup_preserves_original_journal_before_any_source_recovery(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    old_state(path)
    journal = Path(str(path) + "-journal")
    await asyncio.to_thread(journal.write_bytes, b"original unfinished journal bytes")
    before = path.read_bytes(), await asyncio.to_thread(journal.read_bytes)
    database = PersistentDatabase(path)
    await database.open_existing("backup")
    try:
        copied = await StateMaintenance(database).backup(tmp_path / "backup.sqlite3")
        assert tuple(item.read_bytes() for item in copied) == before
    finally:
        await database.close()
    assert (path.read_bytes(), await asyncio.to_thread(journal.read_bytes)) == before


async def seed_abandoned_action(database: PersistentDatabase) -> str:
    """Create future action lifecycle rows without implementing action workflows in this task."""
    identity = str(uuid4())

    def seed(session: Session) -> None:
        """Persist execution protection and audit with no dependency on a saved investigation."""
        session.add(
            PreparedActionRow(
                id=identity,
                actor="alice",
                host="local",
                container_id="a" * 64,
                phase="dispatching",
                snapshot="{}",
            )
        )
        session.flush()
        session.add(TargetGuardRow(host="local", container_id="a" * 64, active_action_id=identity))
        session.add(
            ActionAuditRow(
                event="action.claimed",
                occurred_at=datetime.now(UTC).isoformat(),
                actor="alice",
                action_id=identity,
                fields="{}",
            )
        )

    await database.transaction(seed, write=True)
    return identity


async def test_reconcile_construction_does_not_run_server_recovery(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    database = PersistentDatabase(path)
    await database.initialize_server()
    await seed_abandoned_action(database)
    await database.close()
    before = path.read_bytes()

    def forbidden(session: Session) -> RecoveryReport:
        """Detect any accidental normal-startup recovery during maintenance construction."""
        raise AssertionError("Reconcile must not run startup recovery")

    maintenance = PersistentDatabase(path, recoveries=(forbidden,))
    await maintenance.open_existing("reconcile")
    await maintenance.close()
    assert path.read_bytes() == before


async def test_server_refuses_abandoned_work_without_recovery_service(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    database = PersistentDatabase(path)
    await database.initialize_server()
    await seed_abandoned_action(database)
    await database.close()
    reopened = PersistentDatabase(path)
    try:
        with pytest.raises(StorageError) as caught:
            await reopened.initialize_server()
        assert caught.value.code == "recovery_required"
        assert not reopened.healthy
    finally:
        await reopened.close()


async def test_archive_survives_close_and_offline_migrate_does_no_recovery(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    database = PersistentDatabase(path)
    await database.initialize_server()
    identity = str(uuid4())
    await SQLiteInvestigations(database).create("alice", identity, "local", datetime.now(UTC))
    await database.close()
    maintenance = PersistentDatabase(path)
    await maintenance.open_existing("migrate")
    await maintenance.migrate()
    await maintenance.close()
    reopened = PersistentDatabase(path)
    await reopened.initialize_server()
    try:
        assert (await SQLiteInvestigations(reopened).read("alice", identity)).host == "local"
    finally:
        await reopened.close()
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (HEAD,)
