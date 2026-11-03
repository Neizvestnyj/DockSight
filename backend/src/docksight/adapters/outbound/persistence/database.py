import asyncio
import sqlite3
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import portalocker
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from docksight.adapters.outbound.persistence.rows import PreparedActionRow, TurnRow
from docksight.application.investigations.errors import StorageError
from docksight.domain.errors import DockSightError

type MaintenanceMode = Literal["status", "backup", "migrate", "reconcile"]
HEAD: Final = "0001_state"


@dataclass(frozen=True)
class RecoveryReport:
    """Report committed startup recovery performed by registered adapter callbacks."""

    interrupted_turns: int = 0
    failed_actions: int = 0
    indeterminate_actions: int = 0
    revoked_sessions: int = 0


type Recovery = Callable[[Session], RecoveryReport]


def _connect(path: Path) -> sqlite3.Connection:
    """Enable modern transaction control after setting connection-level durability pragmas."""
    connection = sqlite3.connect(path, timeout=2, autocommit=False)
    try:
        connection.autocommit = True
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.autocommit = False
    except BaseException:
        connection.close()
        raise
    return connection


async def _settled[T](future: asyncio.Future[T]) -> T:
    """Await accepted work through caller cancellation without misreporting its commit outcome."""
    while True:
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            if future.cancelled():
                raise


class PersistentDatabase:
    """Own one local database, lifetime OS lock, worker thread, and bounded admission queue."""

    def __init__(self, path: Path, recoveries: Sequence[Recovery] = ()) -> None:
        """Canonicalize ownership before any SQLite connection or application recovery exists."""
        self.path = path.resolve()
        self.recoveries = tuple(recoveries)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="docksight-state")
        self._pending = asyncio.Semaphore(32)
        self._lock: portalocker.Lock | None = None
        self._engine: Engine | None = None
        self._connection: Connection | None = None
        self._mode: MaintenanceMode | None = None
        self._healthy = False
        self._closed = False

    @property
    def healthy(self) -> bool:
        """Expose admission health without querying storage on the event loop."""
        return self._healthy and not self._closed

    async def _dispatch[T](self, operation: Callable[[], T]) -> T:
        """Execute lifecycle work on the same dedicated thread as all transactions."""
        future = asyncio.get_running_loop().run_in_executor(self._executor, operation)
        return await _settled(future)

    def _acquire(self, *, create: bool) -> None:
        """Acquire canonical-path process ownership before inspecting or changing state files."""
        if self._lock is not None or self._closed:
            raise StorageError("storage_lifecycle", "Storage has already been opened or closed")
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        elif not self.path.is_file():
            raise StorageError("storage_missing", "Persistent state file does not exist")
        lock = portalocker.Lock(str(self.path) + ".lock", mode="a+b", timeout=0)
        try:
            lock.acquire()
        except portalocker.exceptions.LockException as error:
            raise StorageError("storage_locked", "Persistent state is owned by another process") from error
        self._lock = lock

    def _open(self) -> None:
        """Create and retain exactly one connection on its owning thread."""
        self._engine = create_engine("sqlite+pysqlite://", creator=lambda: _connect(self.path), poolclass=StaticPool)
        self._connection = self._engine.connect()
        result = self._connection.exec_driver_sql("PRAGMA quick_check").scalar_one()
        self._connection.rollback()
        if result != "ok":
            raise StorageError("storage_corrupt", "Persistent state integrity check failed")

    def _revision(self) -> str | None:
        """Inspect schema compatibility before permitting migrations or writes."""
        connection = self._require_connection()
        exists = connection.exec_driver_sql(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).scalar_one()
        revision = (
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one_or_none()
            if exists
            else None
        )
        connection.rollback()
        return str(revision) if revision is not None else None

    def _upgrade(self) -> None:
        """Apply packaged forward migrations inside an explicit rollback-capable transaction."""
        revision = self._revision()
        if revision not in {None, HEAD}:
            raise StorageError("storage_schema_unsupported", "Persistent schema revision is unsupported")
        connection = self._require_connection()
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        config.attributes["connection"] = connection
        with connection.begin():
            command.upgrade(config, "head")

    def _require_connection(self) -> Connection:
        """Reject transaction use before a supported SQLite connection has been opened."""
        if self._connection is None:
            raise StorageError("storage_lifecycle", "Storage is not open for transactions")
        return self._connection

    async def initialize_server(self) -> RecoveryReport:
        """Migrate and atomically invoke available recovery services before admitting writes."""

        def initialize() -> RecoveryReport:
            """Keep opening, migration, and readiness checks entirely on the database thread."""
            self._acquire(create=True)
            self._open()
            self._upgrade()
            return self._transaction(self._recover)

        try:
            report = await self._dispatch(initialize)
        except DockSightError:
            raise
        except Exception as error:
            raise StorageError() from error
        self._healthy = True
        return report

    def _recover(self, session: Session) -> RecoveryReport:
        """Run registered recovery atomically and refuse readiness if abandoned work remains."""
        reports = [recover(session) for recover in self.recoveries]
        session.flush()
        running = session.scalar(select(TurnRow.id).where(TurnRow.state == "running").limit(1))
        claimed = session.scalar(
            select(PreparedActionRow.id).where(PreparedActionRow.phase.in_(("claimed", "dispatching"))).limit(1)
        )
        if running or claimed:
            raise StorageError("recovery_required", "Abandoned work requires a supported recovery service")
        return RecoveryReport(
            interrupted_turns=sum(report.interrupted_turns for report in reports),
            failed_actions=sum(report.failed_actions for report in reports),
            indeterminate_actions=sum(report.indeterminate_actions for report in reports),
            revoked_sessions=sum(report.revoked_sessions for report in reports),
        )

    async def open_existing(self, mode: MaintenanceMode) -> None:
        """Acquire offline ownership without migrations, recovery, cleanup, or server construction."""
        if mode not in {"status", "backup", "migrate", "reconcile"}:
            raise StorageError("storage_mode", "Unsupported maintenance mode")

        def open_mode() -> None:
            """Keep status and raw backup completely free of source SQLite opening."""
            self._acquire(create=False)
            self._mode = mode
            if mode in {"status", "backup"}:
                return
            self._open()
            revision = self._revision()
            if revision not in {None, HEAD} or (mode == "reconcile" and revision != HEAD):
                raise StorageError("storage_schema_unsupported", "Persistent schema revision is unsupported")

        try:
            await self._dispatch(open_mode)
        except DockSightError:
            raise
        except Exception as error:
            raise StorageError() from error
        self._healthy = True

    async def migrate(self) -> None:
        """Run only the explicitly requested offline forward migration."""
        if self._mode != "migrate" or not self.healthy:
            raise StorageError("storage_mode", "Migrations require migrate maintenance mode")
        try:
            await self._dispatch(self._upgrade)
        except Exception as error:
            self._healthy = False
            if isinstance(error, DockSightError):
                raise
            raise StorageError() from error

    def _transaction[T](self, operation: Callable[[Session], T]) -> T:
        """Materialize results before closing the short adapter-owned transaction."""
        with Session(self._require_connection(), expire_on_commit=False) as session, session.begin():
            return operation(session)

    def _execute[T](self, operation: Callable[[Session], T], *, write: bool) -> T:
        """Trip admission on the worker before a later queued mutation can start."""
        if write and not self.healthy:
            raise StorageError()
        try:
            return self._transaction(operation)
        except DockSightError:
            raise
        except Exception as error:
            self._healthy = False
            raise StorageError() from error

    async def transaction[T](self, operation: Callable[[Session], T], *, write: bool = False) -> T:
        """Admit bounded work and await an accepted transaction until its outcome is known."""
        if self._closed or self._connection is None or (write and not self.healthy):
            raise StorageError()
        if self._mode in {"status", "backup", "migrate"}:
            raise StorageError("storage_mode", "This maintenance mode does not admit archive transactions")
        try:
            await asyncio.wait_for(self._pending.acquire(), timeout=2)
        except TimeoutError as error:
            raise StorageError("storage_busy", "Persistent storage admission timed out") from error
        try:
            return await self._dispatch(lambda: self._execute(operation, write=write))
        except DockSightError:
            raise
        except Exception as error:
            self._healthy = False
            raise StorageError() from error
        finally:
            self._pending.release()

    async def maintenance[T](self, mode: MaintenanceMode, operation: Callable[[], T]) -> T:
        """Execute an offline file operation only under its matching process-owned maintenance mode."""
        if self._mode != mode or not self.healthy:
            raise StorageError("storage_mode", f"Operation requires {mode} maintenance mode")
        return await self._dispatch(operation)

    async def close(self) -> None:
        """Drain queued transactions, close the owned connection, and release process ownership."""
        if self._closed:
            return
        self._closed = True
        self._healthy = False

        def dispose() -> None:
            """Release resources on their owning thread after all earlier submitted operations."""
            try:
                if self._connection is not None:
                    self._connection.close()
                if self._engine is not None:
                    self._engine.dispose()
            finally:
                if self._lock is not None:
                    self._lock.release()

        await self._dispatch(dispose)
        self._executor.shutdown(wait=False)
