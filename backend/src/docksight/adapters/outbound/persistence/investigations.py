from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from docksight.adapters.outbound.persistence.codec import (
    decode_cursor,
    decode_turn,
    decode_value,
    encode_cursor,
    page_limit,
    patch_value,
    utc_text,
)
from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.adapters.outbound.persistence.rows import (
    ActorWorkspaceRow,
    InvestigationRow,
    SubmissionReceiptRow,
    TurnRow,
)
from docksight.application.investigations.contracts import (
    ActorWorkspace,
    ActorWorkspacePatch,
    InvestigationPage,
    InvestigationSummary,
    InvestigationView,
    InvestigationWorkspace,
    SavedTurn,
    StorageLimits,
    TurnPage,
    UnsupportedTurn,
    WorkspacePatch,
)
from docksight.application.investigations.errors import HistoryError, capacity, not_found
from docksight.domain.errors import ErrorKind


def _owned(session: Session, actor: str, identity: str) -> InvestigationRow:
    """Resolve exact archive ownership before reading workspace or turn content."""
    row = session.scalar(
        select(InvestigationRow).where(InvestigationRow.id == identity, InvestigationRow.actor == actor)
    )
    if row is None:
        raise not_found()
    return row


def _view(session: Session, row: InvestigationRow) -> InvestigationView:
    """Materialize owned values while the ORM session remains confined to its worker."""
    count = session.scalar(select(func.count()).select_from(TurnRow).where(TurnRow.investigation_id == row.id)) or 0
    return InvestigationView(
        id=row.id,
        host=row.host,
        title=row.title,
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
        active_turn_id=row.active_turn_id,
        turn_count=count,
        workspace=decode_value(InvestigationWorkspace, row.workspace),
    )


def _actor_workspace(session: Session, actor: str) -> ActorWorkspace:
    """Read preferences independently of diagnostic workspace revisions."""
    row = session.get(ActorWorkspaceRow, actor)
    return decode_value(ActorWorkspace, row.workspace) if row else ActorWorkspace()


def _save_actor_workspace(session: Session, actor: str, value: ActorWorkspace, now: str) -> None:
    """Persist an already-validated detached preference snapshot in the current transaction."""
    row = session.get(ActorWorkspaceRow, actor)
    if row is None:
        session.add(ActorWorkspaceRow(actor=actor, workspace=value.model_dump_json(), updated_at=now))
    else:
        row.workspace, row.updated_at = value.model_dump_json(), now


def _turn_item(row: TurnRow) -> SavedTurn | UnsupportedTurn:
    """Report one unsupported envelope without dropping the row or an entire history page."""
    try:
        return decode_turn(row.snapshot)
    except HistoryError:
        return UnsupportedTurn(id=row.id)


class SQLiteInvestigations:
    """Persist complete archive and workspace operations through short serialized transactions."""

    def __init__(self, database: PersistentDatabase, limits: StorageLimits | None = None) -> None:
        """Bind the process-owned database without opening it or changing runtime wiring."""
        self.database = database
        self.limits = limits or StorageLimits()

    async def create(self, actor: str, investigation_id: str, host: str, now: datetime) -> InvestigationView:
        """Create idempotently and enforce actor archive capacity without deleting older history."""
        timestamp = utc_text(now)
        initial = InvestigationView(id=investigation_id, host=host, created_at=now, updated_at=now)

        def create(session: Session) -> InvestigationView:
            """Keep duplicate resolution and capacity checks in the insertion transaction."""
            existing = session.get(InvestigationRow, investigation_id)
            if existing is not None:
                _owned(session, actor, investigation_id)
                if existing.host != host:
                    raise HistoryError(
                        "history_conflict", "Investigation already exists for different input", ErrorKind.CONFLICT
                    )
                return _view(session, existing)
            count = (
                session.scalar(
                    select(func.count()).select_from(InvestigationRow).where(InvestigationRow.actor == actor)
                )
                or 0
            )
            if count >= self.limits.investigations_per_actor:
                raise capacity()
            row = InvestigationRow(
                id=investigation_id,
                actor=actor,
                host=host,
                title="",
                created_at=timestamp,
                updated_at=timestamp,
                workspace=initial.workspace.model_dump_json(),
                context="[]",
                reserved_bytes=0,
            )
            self._check_capacity(session, actor, row, initial.workspace)
            session.add(row)
            return initial

        return await self.database.transaction(create, write=True)

    async def read(self, actor: str, investigation_id: str) -> InvestigationView:
        """Read detached owned archive metadata and its validated workspace."""
        return await self.database.transaction(lambda session: _view(session, _owned(session, actor, investigation_id)))

    async def list_owned(self, actor: str, limit: int = 10, cursor: str | None = None) -> InvestigationPage:
        """Query bounded actor-scoped activity keysets with stable tie-breaking IDs."""
        page_limit(limit)
        before = decode_cursor(actor, "investigations", cursor)

        def listing(session: Session) -> InvestigationPage:
            """Materialize one page and its continuation coordinates within the read transaction."""
            query = select(InvestigationRow).where(InvestigationRow.actor == actor)
            if before:
                query = query.where(
                    or_(
                        InvestigationRow.updated_at < before[0],
                        (InvestigationRow.updated_at == before[0]) & (InvestigationRow.id < before[1]),
                    )
                )
            rows = list(
                session.scalars(
                    query.order_by(InvestigationRow.updated_at.desc(), InvestigationRow.id.desc()).limit(limit + 1)
                )
            )
            selected = rows[:limit]
            cursor = (
                encode_cursor(actor, "investigations", selected[-1].updated_at, selected[-1].id)
                if len(rows) > limit
                else None
            )
            items = tuple(
                InvestigationSummary.model_validate(_view(session, row).model_dump(exclude={"workspace"}))
                for row in selected
            )
            return InvestigationPage(items=items, next_cursor=cursor)

        return await self.database.transaction(listing)

    async def turns(self, actor: str, investigation_id: str, limit: int = 20, cursor: str | None = None) -> TurnPage:
        """Read older immutable turn pages in chronological display order."""
        page_limit(limit)
        scope = f"turns:{investigation_id}"
        before = decode_cursor(actor, scope, cursor)

        def listing(session: Session) -> TurnPage:
            """Check ownership before materializing supported or unsupported per-item snapshots."""
            _owned(session, actor, investigation_id)
            query = select(TurnRow).where(TurnRow.actor == actor, TurnRow.investigation_id == investigation_id)
            if before:
                query = query.where(
                    or_(TurnRow.created_at < before[0], (TurnRow.created_at == before[0]) & (TurnRow.id < before[1]))
                )
            rows = list(session.scalars(query.order_by(TurnRow.created_at.desc(), TurnRow.id.desc()).limit(limit + 1)))
            selected = rows[:limit]
            cursor = (
                encode_cursor(actor, scope, selected[-1].created_at, selected[-1].id) if len(rows) > limit else None
            )
            return TurnPage(items=tuple(_turn_item(row) for row in reversed(selected)), next_cursor=cursor)

        return await self.database.transaction(listing)

    async def read_turn(self, actor: str, turn_id: str) -> SavedTurn:
        """Return only a validated owned snapshot and keep foreign IDs indistinguishable."""

        def read(session: Session) -> SavedTurn:
            """Check both turn ownership and its owning investigation before decoding content."""
            row = session.scalar(select(TurnRow).where(TurnRow.id == turn_id, TurnRow.actor == actor))
            if row is None:
                raise not_found()
            _owned(session, actor, row.investigation_id)
            return decode_turn(row.snapshot)

        return await self.database.transaction(read)

    async def patch_workspace(
        self, actor: str, investigation_id: str, patch: WorkspacePatch, now: datetime
    ) -> InvestigationWorkspace:
        """Atomically compare workspace revisions and preserve existing history on capacity failure."""
        timestamp = utc_text(now)

        def patching(session: Session) -> InvestigationWorkspace:
            """Count UTF-8 bytes and reservations before saving the replacement workspace."""
            row = _owned(session, actor, investigation_id)
            updated = patch_value(decode_value(InvestigationWorkspace, row.workspace), patch)
            self._check_capacity(session, actor, row, updated)
            row.workspace, row.updated_at = updated.model_dump_json(), timestamp
            return updated

        return await self.database.transaction(patching, write=True)

    def _check_capacity(
        self, session: Session, actor: str, current: InvestigationRow, workspace: InvestigationWorkspace
    ) -> None:
        """Include saved snapshots, workspace JSON, and retained turn reservations in byte accounting."""
        rows = list(session.scalars(select(InvestigationRow).where(InvestigationRow.actor == actor)))
        sizes: dict[str, int] = {}
        for row in rows:
            snapshots = (
                session.scalar(select(func.sum(TurnRow.snapshot_bytes)).where(TurnRow.investigation_id == row.id)) or 0
            )
            sizes[row.id] = len(row.workspace.encode()) + len(row.context.encode()) + row.reserved_bytes + snapshots
        if current.id not in sizes:
            sizes[current.id] = len(current.context.encode()) + current.reserved_bytes
        else:
            sizes[current.id] -= len(current.workspace.encode())
        sizes[current.id] += len(workspace.model_dump_json().encode())
        if sizes[current.id] > self.limits.investigation_bytes or sum(sizes.values()) > self.limits.actor_bytes:
            raise capacity()

    async def workspace(self, actor: str) -> ActorWorkspace:
        """Read actor preferences independently of any investigation's draft revision."""
        return await self.database.transaction(lambda session: _actor_workspace(session, actor))

    async def patch_actor_workspace(self, actor: str, patch: ActorWorkspacePatch, now: datetime) -> ActorWorkspace:
        """Compare actor preference revisions and validate last-active ownership in one transaction."""
        timestamp = utc_text(now)

        def patching(session: Session) -> ActorWorkspace:
            """Resolve any referenced archive before saving independently revisioned preferences."""
            updated = patch_value(_actor_workspace(session, actor), patch)
            if updated.last_investigation_id is not None:
                _owned(session, actor, updated.last_investigation_id)
            _save_actor_workspace(session, actor, updated, timestamp)
            return updated

        return await self.database.transaction(patching, write=True)

    async def delete(self, actor: str, investigation_id: str, now: datetime) -> None:
        """Delete inactive owned content and tombstone receipts without touching action protection."""
        timestamp = utc_text(now)

        def deleting(session: Session) -> None:
            """Choose the next owned last-active archive and retain content-free duplicate receipts."""
            row = _owned(session, actor, investigation_id)
            running = session.scalar(
                select(TurnRow.id)
                .where(TurnRow.investigation_id == investigation_id, TurnRow.state == "running")
                .limit(1)
            )
            if row.active_turn_id or running:
                raise HistoryError("turn_busy", "Investigation has a running turn", ErrorKind.CONFLICT)
            workspace = _actor_workspace(session, actor)
            session.execute(
                update(SubmissionReceiptRow)
                .where(SubmissionReceiptRow.actor == actor, SubmissionReceiptRow.investigation_id == investigation_id)
                .values(archive_deleted_at=timestamp)
            )
            session.delete(row)
            session.flush()
            if workspace.last_investigation_id == investigation_id:
                next_id = session.scalar(
                    select(InvestigationRow.id)
                    .where(InvestigationRow.actor == actor)
                    .order_by(InvestigationRow.updated_at.desc(), InvestigationRow.id.desc())
                    .limit(1)
                )
                updated = workspace.model_copy(
                    update={"revision": workspace.revision + 1, "last_investigation_id": next_id}
                )
                _save_actor_workspace(session, actor, updated, timestamp)

        await self.database.transaction(deleting, write=True)
