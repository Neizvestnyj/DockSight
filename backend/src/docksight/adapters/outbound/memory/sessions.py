from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from docksight.application.ports.state import Session
from docksight.domain.errors import DockSightError


@dataclass
class Entry:
    """Track a session's idle timestamp and active lease state."""

    session: Session
    touched: datetime
    active: bool = False


class MemorySessions:
    """Store bounded actor-and-host-scoped history with exclusive turn leases."""

    def __init__(
        self,
        capacity: int = 100,
        ttl: int = 1800,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Configure session capacity, idle retention, and the expiry clock."""
        self._entries: dict[str, Entry] = {}
        self._capacity = capacity
        self._ttl = timedelta(seconds=ttl)
        self._clock = clock

    @asynccontextmanager
    async def lease(self, session_id: str | None, actor: str, host: str) -> AsyncGenerator[Session]:
        """Lease one scoped session and trim history when its turn finishes."""
        now = self._clock()
        self._expire(now)
        if session_id is None:
            if len(self._entries) >= self._capacity:
                raise DockSightError("session_capacity", "Session capacity reached; retry later", 503)
            session_id = str(uuid4())
            self._entries[session_id] = Entry(Session(session_id, actor, host), now)
        entry = self._entries.get(session_id)
        if entry is None or entry.session.actor != actor or entry.session.host != host:
            raise DockSightError("session_not_found", "Session not found for this actor and host", 404)
        if entry.active:
            raise DockSightError("session_busy", "A turn is already running in this session", 409)
        entry.active = True
        try:
            yield entry.session
        finally:
            _trim_history(entry.session)
            entry.active = False
            entry.touched = self._clock()

    def _expire(self, now: datetime) -> None:
        """Evict inactive sessions once their idle lifetime has elapsed."""
        for key, entry in list(self._entries.items()):
            if not entry.active and now - entry.touched >= self._ttl:
                del self._entries[key]


def _trim_history(session: Session) -> None:
    """Drop complete user/assistant pairs until history fits both retention limits."""
    while len(session.history) > 20 or sum(len(row.content) for row in session.history) > 32000:
        del session.history[:2]
