import asyncio
from pathlib import Path
from typing import BinaryIO

import pytest

from docksight.adapters.outbound.persistence import maintenance
from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.adapters.outbound.persistence.maintenance import StateMaintenance
from docksight.application.investigations.errors import StorageError


async def test_backup_refuses_the_sources_absent_journal_path(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    server = PersistentDatabase(path)
    await server.initialize_server()
    await server.close()
    original = path.read_bytes()
    journal = Path(str(path) + "-journal")
    database = PersistentDatabase(path)
    await database.open_existing("backup")
    try:
        with pytest.raises(StorageError) as caught:
            await StateMaintenance(database).backup(journal)
        assert caught.value.code == "storage_backup_exists"
        assert path.read_bytes() == original
        assert not await asyncio.to_thread(journal.exists)
    finally:
        await database.close()


async def test_backup_refuses_an_unrelated_destination_journal_without_creating_main(tmp_path: Path) -> None:
    source, destination = tmp_path / "state.sqlite3", tmp_path / "backup.sqlite3"
    server = PersistentDatabase(source)
    await server.initialize_server()
    await server.close()
    journal = Path(str(destination) + "-journal")
    await asyncio.to_thread(journal.write_bytes, b"unrelated journal")
    database = PersistentDatabase(source)
    await database.open_existing("backup")
    try:
        with pytest.raises(StorageError, match="Backup destination must not exist"):
            await StateMaintenance(database).backup(destination)
        assert not await asyncio.to_thread(destination.exists)
        assert await asyncio.to_thread(journal.read_bytes) == b"unrelated journal"
    finally:
        await database.close()


@pytest.mark.parametrize("failure", [1, 2])
async def test_failed_backup_removes_only_its_partial_main_and_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: int
) -> None:
    source, destination = tmp_path / "state.sqlite3", tmp_path / "backup.sqlite3"
    await asyncio.to_thread(source.write_bytes, b"main")
    source_journal = Path(str(source) + "-journal")
    await asyncio.to_thread(source_journal.write_bytes, b"journal")
    calls = 0

    def copy(incoming: BinaryIO, outgoing: BinaryIO) -> None:
        """Write partial bytes before failing the selected owned destination copy."""
        nonlocal calls
        calls += 1
        outgoing.write(incoming.read(1))
        if calls == failure:
            raise OSError("full disk")

    monkeypatch.setattr(maintenance.shutil, "copyfileobj", copy)
    database = PersistentDatabase(source)
    await database.open_existing("backup")
    try:
        with pytest.raises(StorageError) as caught:
            await StateMaintenance(database).backup(destination)
        assert caught.value.code == "storage_backup_failed"
        assert not await asyncio.to_thread(destination.exists)
        assert not await asyncio.to_thread(Path(str(destination) + "-journal").exists)
        assert source.read_bytes() == b"main"
        assert await asyncio.to_thread(source_journal.read_bytes) == b"journal"
    finally:
        await database.close()
