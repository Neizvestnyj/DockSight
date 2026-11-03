import asyncio
from pathlib import Path

import pytest

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
