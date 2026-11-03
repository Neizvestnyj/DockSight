import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from docksight.domain.actions import ActionState, PreparedAction
from docksight.domain.errors import DockSightError, ErrorKind


class MemoryActions:
    """Keep bounded action state, atomic claims, and per-target mutation locks."""

    def __init__(
        self,
        capacity: int = 1000,
        retention: int = 1800,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Configure action retention, capacity, and the clock used for expiry."""
        self._entries: dict[str, PreparedAction] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._references: dict[tuple[str, str], int] = {}
        self._blocked: set[tuple[str, str]] = set()
        self._capacity = capacity
        self._retention = timedelta(seconds=retention)
        self._clock = clock

    async def add(self, action: PreparedAction) -> None:
        """Retain a prepared action after evicting eligible expired entries."""
        now = self._clock()
        for key, item in list(self._entries.items()):
            if item.state != ActionState.RUNNING and now >= item.expires_at + self._retention:
                del self._entries[key]
        if action.id in self._entries:
            raise DockSightError("action_conflict", "Action already exists", ErrorKind.CONFLICT)
        if len(self._entries) >= self._capacity or len(self._blocked) >= self._capacity:
            raise DockSightError("action_capacity", "Action capacity reached; retry later", ErrorKind.UNAVAILABLE)
        self._entries[action.id] = action

    async def get(self, action_id: str, actor: str) -> PreparedAction:
        """Resolve an action only for its owning actor."""
        item = self._entries.get(action_id)
        if item is None or item.actor != actor:
            raise DockSightError("action_not_found", "Action not found", ErrorKind.NOT_FOUND)

        return item

    async def claim(
        self,
        action_id: str,
        actor: str,
        key: str,
        confirmed: bool,
        now: datetime,
    ) -> tuple[PreparedAction, bool]:
        """Atomically claim an action or return its existing idempotent result."""
        item = await self.get(action_id, actor)

        return item, item.claim(actor, key, confirmed, now)

    @asynccontextmanager
    async def target_lock(self, host: str, container_id: str) -> AsyncGenerator[None]:
        """Serialize mutations and reject targets with an ambiguous prior outcome."""
        target = (host, container_id)
        lock = self._locks.setdefault(target, asyncio.Lock())
        self._references[target] = self._references.get(target, 0) + 1
        try:
            async with lock:
                if target in self._blocked:
                    raise DockSightError(
                        "target_indeterminate",
                        "Inspect Docker and reconcile the previous action before restarting this backend",
                        ErrorKind.CONFLICT,
                    )
                yield
        finally:
            self._references[target] -= 1
            if self._references[target] == 0:
                del self._references[target]
                del self._locks[target]

    async def block_target(self, host: str, container_id: str) -> None:
        """Prevent further mutations after an indeterminate Docker outcome."""
        self._blocked.add((host, container_id))
