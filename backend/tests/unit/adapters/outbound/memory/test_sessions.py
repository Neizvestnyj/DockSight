import pytest

from docksight.adapters.outbound.memory.sessions import MemorySessions
from docksight.domain.errors import DockSightError


async def test_session_ownership_and_host_scope_cannot_be_changed() -> None:
    store = MemorySessions()
    async with store.lease(None, "alice", "local") as session:
        session_id = session.id
    with pytest.raises(DockSightError):
        async with store.lease(session_id, "bob", "local"):
            pass
    with pytest.raises(DockSightError):
        async with store.lease(session_id, "alice", "production"):
            pass


async def test_busy_session_cannot_be_evicted_or_mutated_concurrently() -> None:
    store = MemorySessions(capacity=1)
    async with store.lease(None, "alice", "local") as session:
        with pytest.raises(DockSightError):
            async with store.lease(session.id, "alice", "local"):
                pass
        with pytest.raises(DockSightError):
            async with store.lease(None, "alice", "local"):
                pass
