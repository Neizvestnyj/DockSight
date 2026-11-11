import shutil
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.application.investigations.errors import StorageError


@dataclass(frozen=True)
class StateStatus:
    """Describe offline state without opening or recovering the source database."""

    schema_revision: str | None
    recovery_required: bool
    journal_present: bool


class StateMaintenance:
    """Inspect copies and preserve original main/journal bytes under exclusive ownership."""

    def __init__(self, database: PersistentDatabase) -> None:
        """Require the same owner used by the stopped-server maintenance command."""
        self.database = database

    async def status(self) -> StateStatus:
        """Read a disposable immutable copy and report journals without source recovery."""
        return await self.database.maintenance("status", self._status)

    def _status(self) -> StateStatus:
        """Avoid SQLite entirely when a source rollback journal may require recovery."""
        journal = Path(str(self.database.path) + "-journal")
        if journal.exists():
            return StateStatus(None, True, True)
        with tempfile.TemporaryDirectory(prefix="docksight-status-") as temporary:
            copied = Path(temporary) / "state.sqlite3"
            shutil.copyfile(self.database.path, copied)
            try:
                return _inspect_copy(copied)
            except sqlite3.Error as error:
                raise StorageError("storage_corrupt", "Persistent state cannot be inspected") from error

    async def backup(self, destination: Path) -> tuple[Path, ...]:
        """Copy raw state files before any SQLite recovery and refuse overwriting existing files."""
        return await self.database.maintenance("backup", lambda: self._backup(destination.resolve()))

    def _backup(self, destination: Path) -> tuple[Path, ...]:
        """Preserve each original byte and never overwrite the source through an alias."""
        source = self.database.path
        journal = Path(str(source) + "-journal")
        sources = (source, journal) if journal.exists() else (source,)
        targets = tuple(destination if item == source else Path(str(destination) + "-journal") for item in sources)
        protected = {source, journal, Path(str(source) + ".lock")}
        members = (destination, Path(str(destination) + "-journal"))
        if any(target.exists() or target.is_symlink() or target in protected for target in members):
            raise StorageError("storage_backup_exists", "Backup destination must not exist")
        return _copy_backup(sources, targets)


def _copy_backup(sources: tuple[Path, ...], targets: tuple[Path, ...]) -> tuple[Path, ...]:
    """Remove only exclusive-created destination members if a raw backup copy fails."""
    created: list[Path] = []
    try:
        for source, target in zip(sources, targets, strict=True):
            with source.open("rb") as incoming, target.open("xb") as outgoing:
                created.append(target)
                shutil.copyfileobj(incoming, outgoing)
        return targets
    except OSError as error:
        for target in reversed(created):
            target.unlink(missing_ok=True)
        raise StorageError("storage_backup_failed", "Persistent state backup failed") from error


def _inspect_copy(path: Path) -> StateStatus:
    """Inspect compatible tables on a read-only copied database without modifying lifecycle rows."""
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True, autocommit=True)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        revision = (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()
            if "alembic_version" in tables
            else None
        )
        running = (
            connection.execute("SELECT 1 FROM turns WHERE state='running' LIMIT 1").fetchone()
            if "turns" in tables
            else None
        )
        claimed = (
            connection.execute(
                "SELECT 1 FROM prepared_actions WHERE phase IN ('claimed','dispatching') LIMIT 1"
            ).fetchone()
            if "prepared_actions" in tables
            else None
        )
        return StateStatus(revision[0] if revision else None, bool(running or claimed), False)
