from dataclasses import dataclass
from datetime import datetime

from docksight.adapters.outbound.persistence.codec import (
    decode_cursor,
    decode_turn,
    encode_cursor,
    page_limit,
    patch_value,
    utc_text,
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
    TurnState,
    UnsupportedTurn,
    WorkspacePatch,
)
from docksight.application.investigations.errors import HistoryError, capacity, not_found
from docksight.domain.errors import ErrorKind


@dataclass(frozen=True)
class MemoryTurn:
    """Keep an encoded detached snapshot and immutable pagination coordinates."""

    investigation_id: str
    created_at: str
    snapshot: str
    state: TurnState


class MemoryInvestigations:
    """Provide explicit development history with no restart retention or age-based eviction."""

    def __init__(self, limits: StorageLimits | None = None) -> None:
        """Keep archive values private and detached from returned snapshots."""
        self.limits = limits or StorageLimits()
        self._investigations: dict[str, InvestigationView] = {}
        self._turns: dict[str, MemoryTurn] = {}
        self._workspaces: dict[str, ActorWorkspace] = {}
        self._owners: dict[str, str] = {}

    async def create(self, actor: str, investigation_id: str, host: str, now: datetime) -> InvestigationView:
        """Create an archive idempotently within actor/host ownership and capacity."""
        existing = self._investigations.get(investigation_id)
        if existing is not None:
            if self._owners[investigation_id] != actor:
                raise not_found()
            if existing.host != host:
                raise HistoryError(
                    "history_conflict", "Investigation already exists for different input", ErrorKind.CONFLICT
                )
            return self._owned(actor, investigation_id).model_copy(deep=True)
        if sum(owner == actor for owner in self._owners.values()) >= self.limits.investigations_per_actor:
            raise capacity()
        utc_text(now)
        view = InvestigationView(id=investigation_id, host=host, created_at=now, updated_at=now)
        self._check_capacity(actor, investigation_id, view.workspace)
        self._investigations[investigation_id] = view
        self._owners[investigation_id] = actor
        return view.model_copy(deep=True)

    async def read(self, actor: str, investigation_id: str) -> InvestigationView:
        """Return only owned metadata and a detached acknowledged workspace."""
        view = self._owned(actor, investigation_id)
        return view.model_copy(deep=True)

    def _owned(self, actor: str, investigation_id: str) -> InvestigationView:
        """Use one indistinguishable failure for missing and foreign identifiers."""
        if self._owners.get(investigation_id) != actor:
            raise not_found()
        count = sum(row.investigation_id == investigation_id for row in self._turns.values())
        return self._investigations[investigation_id].model_copy(update={"turn_count": count})

    async def list_owned(self, actor: str, limit: int = 10, cursor: str | None = None) -> InvestigationPage:
        """List activity keysets without discarding archives outside the initial page."""
        page_limit(limit)
        before = decode_cursor(actor, "investigations", cursor)
        rows = [self._owned(actor, identity) for identity in self._investigations if self._owners[identity] == actor]
        rows.sort(key=lambda view: (utc_text(view.updated_at), view.id), reverse=True)
        rows = [row for row in rows if before is None or (utc_text(row.updated_at), row.id) < before]
        selected = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = selected[-1]
            next_cursor = encode_cursor(actor, "investigations", utc_text(last.updated_at), last.id)
        items = tuple(InvestigationSummary.model_validate(row.model_dump(exclude={"workspace"})) for row in selected)
        return InvestigationPage(items=items, next_cursor=next_cursor)

    async def turns(self, actor: str, investigation_id: str, limit: int = 20, cursor: str | None = None) -> TurnPage:
        """Read chronological pages and preserve unsupported items as typed errors."""
        self._owned(actor, investigation_id)
        page_limit(limit)
        query = f"turns:{investigation_id}"
        before = decode_cursor(actor, query, cursor)
        rows = [(identity, row) for identity, row in self._turns.items() if row.investigation_id == investigation_id]
        rows.sort(key=lambda item: (item[1].created_at, item[0]), reverse=True)
        rows = [row for row in rows if before is None or (row[1].created_at, row[0]) < before]
        selected = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            identity, last = selected[-1]
            next_cursor = encode_cursor(actor, query, last.created_at, identity)
        return TurnPage(
            items=tuple(self._turn_item(identity, row) for identity, row in reversed(selected)), next_cursor=next_cursor
        )

    def _turn_item(self, identity: str, row: MemoryTurn) -> SavedTurn | UnsupportedTurn:
        """Expose unreadable history without removing its encoded bytes."""
        try:
            return decode_turn(row.snapshot)
        except HistoryError:
            return UnsupportedTurn(id=identity)

    async def read_turn(self, actor: str, turn_id: str) -> SavedTurn:
        """Read a detached owned snapshot through the supported version dispatcher."""
        row = self._turns.get(turn_id)
        if row is None:
            raise not_found()
        self._owned(actor, row.investigation_id)
        return decode_turn(row.snapshot)

    async def patch_workspace(
        self, actor: str, investigation_id: str, patch: WorkspacePatch, now: datetime
    ) -> InvestigationWorkspace:
        """Compare revisions and account for UTF-8 workspace bytes before saving."""
        view = self._owned(actor, investigation_id)
        updated = patch_value(view.workspace, patch)
        self._check_capacity(actor, investigation_id, updated)
        utc_text(now)
        self._investigations[investigation_id] = view.model_copy(update={"workspace": updated, "updated_at": now})
        return updated.model_copy(deep=True)

    def _check_capacity(self, actor: str, identity: str, workspace: InvestigationWorkspace) -> None:
        """Check existing content and seeded context before creating or replacing a workspace."""
        sizes = {
            key: len(view.workspace.model_dump_json().encode())
            + len(b"[]")
            + sum(len(row.snapshot.encode()) for row in self._turns.values() if row.investigation_id == key)
            for key, view in self._investigations.items()
            if self._owners[key] == actor
        }
        previous = self._investigations.get(identity)
        if previous is None:
            sizes[identity] = len(b"[]")
        else:
            sizes[identity] -= len(previous.workspace.model_dump_json().encode())
        sizes[identity] += len(workspace.model_dump_json().encode())
        if sizes[identity] > self.limits.investigation_bytes or sum(sizes.values()) > self.limits.actor_bytes:
            raise capacity()

    async def workspace(self, actor: str) -> ActorWorkspace:
        """Return independent detached actor preferences or the revision-zero default."""
        return self._workspaces.get(actor, ActorWorkspace()).model_copy(deep=True)

    async def patch_actor_workspace(self, actor: str, patch: ActorWorkspacePatch, now: datetime) -> ActorWorkspace:
        """Validate last-active ownership and compare actor preference revisions atomically."""
        current = await self.workspace(actor)
        updated = patch_value(current, patch)
        if updated.last_investigation_id is not None:
            self._owned(actor, updated.last_investigation_id)
        utc_text(now)
        self._workspaces[actor] = updated
        return updated.model_copy(deep=True)

    async def delete(self, actor: str, investigation_id: str, now: datetime) -> None:
        """Delete owned inactive content and choose the next owned active preference."""
        view = self._owned(actor, investigation_id)
        running = any(
            row.state == "running" for row in self._turns.values() if row.investigation_id == investigation_id
        )
        if view.active_turn_id or running:
            raise HistoryError("turn_busy", "Investigation has a running turn", ErrorKind.CONFLICT)
        utc_text(now)
        del self._investigations[investigation_id]
        del self._owners[investigation_id]
        self._turns = {
            identity: row for identity, row in self._turns.items() if row.investigation_id != investigation_id
        }
        workspace = await self.workspace(actor)
        if workspace.last_investigation_id == investigation_id:
            page = await self.list_owned(actor, 1)
            identity = page.items[0].id if page.items else None
            self._workspaces[actor] = workspace.model_copy(
                update={"revision": workspace.revision + 1, "last_investigation_id": identity}
            )
