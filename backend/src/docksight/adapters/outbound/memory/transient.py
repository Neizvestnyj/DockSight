from datetime import UTC, datetime, timedelta

from docksight.adapters.outbound.memory.investigations import MemoryInvestigations
from docksight.application.investigations.contracts import InvestigationPage, InvestigationView, SavedTurn, TurnPage
from docksight.domain.errors import DockSightError, ErrorKind


class TransientInvestigations(MemoryInvestigations):
    """Preserve explicit memory-mode idle expiry and global session capacity without affecting SQLite."""

    def __init__(self, capacity: int, ttl: int) -> None:
        """Apply the legacy development retention policy only to inactive in-memory investigations."""
        super().__init__()
        self.capacity, self.ttl = capacity, timedelta(seconds=ttl)
        self._cleaning = False

    async def _expire(self) -> None:
        """Delete inactive expired content through the normal owned deletion and receipt semantics."""
        if self._cleaning:
            return
        self._cleaning = True
        try:
            now = datetime.now(UTC)
            expired = [
                view
                for view in self.history.investigations.values()
                if view.active_turn_id is None and now - view.updated_at >= self.ttl
            ]
            for view in expired:
                await super().delete(self.history.owners[view.id], view.id, now)
        finally:
            self._cleaning = False

    async def create(self, actor: str, investigation_id: str, host: str, now: datetime) -> InvestigationView:
        """Expire inactive sessions and reject capacity before creating another transient investigation."""
        await self._expire()
        if investigation_id not in self.history.investigations and len(self.history.investigations) >= self.capacity:
            raise DockSightError("session_capacity", "Session capacity reached; retry later", ErrorKind.UNAVAILABLE)
        return await super().create(actor, investigation_id, host, now)

    async def read(self, actor: str, investigation_id: str) -> InvestigationView:
        """Refuse continuation of an expired memory-only session without substituting another ID."""
        await self._expire()
        return await super().read(actor, investigation_id)

    async def list_owned(self, actor: str, limit: int = 10, cursor: str | None = None) -> InvestigationPage:
        """List remaining transient history after applying its configured idle policy."""
        await self._expire()
        return await super().list_owned(actor, limit, cursor)

    async def read_turn(self, actor: str, turn_id: str) -> SavedTurn:
        """Read a detached snapshot only while its memory-only investigation remains retained."""
        await self._expire()
        return await super().read_turn(actor, turn_id)

    async def turns(self, actor: str, investigation_id: str, limit: int = 20, cursor: str | None = None) -> TurnPage:
        """Page retained transient turns without changing SQLite archive retention."""
        await self._expire()
        return await super().turns(actor, investigation_id, limit, cursor)
