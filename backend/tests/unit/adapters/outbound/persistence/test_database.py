import asyncio
import threading
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.application.investigations.errors import StorageError


async def test_database_transactions_commit_rollback_and_stay_on_one_thread(tmp_path: Path) -> None:
    database = PersistentDatabase(tmp_path / "state.sqlite3")
    await database.initialize_server()
    try:
        first = await database.transaction(lambda session: threading.get_ident())
        second = await database.transaction(lambda session: threading.get_ident())
        assert first == second != threading.get_ident()

        def fail(session: Session) -> None:
            """Exercise real DDL rollback before storage admission fails closed."""
            session.execute(text("CREATE TABLE must_rollback (id INTEGER)"))
            raise OSError("disk failure")

        with pytest.raises(StorageError):
            await database.transaction(fail, write=True)
        assert not database.healthy
        assert (
            await database.transaction(
                lambda session: session.execute(
                    text("SELECT count(*) FROM sqlite_master WHERE name='must_rollback'")
                ).scalar_one()
            )
            == 0
        )
        with pytest.raises(StorageError):
            await database.transaction(lambda session: None, write=True)
    finally:
        await database.close()


async def test_accepted_cancellation_waits_for_commit_and_keeps_loop_responsive(tmp_path: Path) -> None:
    database = PersistentDatabase(tmp_path / "state.sqlite3")
    await database.initialize_server()
    entered, release = threading.Event(), threading.Event()

    def write(session: Session) -> str:
        """Block a worker transaction until the event loop proves it remains responsive."""
        session.execute(text("CREATE TABLE committed (value TEXT)"))
        session.execute(text("INSERT INTO committed VALUES ('saved')"))
        entered.set()
        assert release.wait(5)
        return "saved"

    try:
        pending = asyncio.create_task(database.transaction(write, write=True))
        assert await asyncio.to_thread(entered.wait, 5)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
        release.set()
        assert await pending == "saved"
        assert (
            await database.transaction(
                lambda session: session.execute(text("SELECT value FROM committed")).scalar_one()
            )
            == "saved"
        )
    finally:
        release.set()
        await database.close()


async def test_queued_writes_fail_closed_after_an_earlier_transaction_fails(tmp_path: Path) -> None:
    database = PersistentDatabase(tmp_path / "state.sqlite3")
    await database.initialize_server()
    entered, release = threading.Event(), threading.Event()

    def fail(session: Session) -> None:
        """Hold a failing transaction long enough for another mutation to queue behind it."""
        entered.set()
        assert release.wait(5)
        raise OSError("disk unavailable")

    def forbidden(session: Session) -> None:
        """Make any mutation admitted after storage failure externally visible."""
        session.execute(text("CREATE TABLE forbidden (id INTEGER)"))

    try:
        failed = asyncio.create_task(database.transaction(fail, write=True))
        assert await asyncio.to_thread(entered.wait, 5)
        queued = asyncio.create_task(database.transaction(forbidden, write=True))
        await asyncio.sleep(0)
        release.set()
        for pending in (failed, queued):
            with pytest.raises(StorageError):
                await pending
        assert (
            await database.transaction(
                lambda session: session.execute(
                    text("SELECT count(*) FROM sqlite_master WHERE name='forbidden'")
                ).scalar_one()
            )
            == 0
        )
    finally:
        release.set()
        await database.close()
