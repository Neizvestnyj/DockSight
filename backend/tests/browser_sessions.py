import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from docksight.application.ports.browser_sessions import BrowserSession, BrowserSessionStore


async def assert_bounded_browser_session_cleanup(store: BrowserSessionStore) -> None:
    """Run the same expiry, revocation, batching, and live-preservation checks against real stores."""
    now = datetime(2026, 11, 4, tzinfo=UTC)
    idle_before = now - timedelta(hours=1)
    live = BrowserSession(
        token_hash="f" * 64,
        actor="alice",
        credential_fingerprint="e" * 64,
        created_at=now - timedelta(hours=8),
        last_seen_at=idle_before + timedelta(microseconds=1),
        expires_at=now + timedelta(microseconds=1),
    )
    await store.add(live)
    stale: list[BrowserSession] = []
    for index in range(205):
        record = live.model_copy(
            update={
                "token_hash": hashlib.sha256(str(index).encode()).hexdigest(),
                "last_seen_at": idle_before if index % 3 == 1 else now,
                "expires_at": now if index % 3 == 0 else now + timedelta(hours=1),
                "revoked_at": now if index % 3 == 2 else None,
            }
        )
        stale.append(record)
        await store.add(record)
    for limit in (-1, 0, 101):
        with pytest.raises(ValueError, match=r"1.*100"):
            await store.cleanup(now, idle_before, limit=limit)
    assert all([await store.get(record.token_hash) == record for record in stale])
    assert await store.cleanup(now, idle_before) == 100
    assert await store.get(live.token_hash) == live
    assert await store.cleanup(now, idle_before, limit=7) == 7
    assert await store.get(live.token_hash) == live
    assert await store.cleanup(now, idle_before) == 98
    assert await store.cleanup(now, idle_before) == 0
    assert all([await store.get(record.token_hash) is None for record in stale])
    assert await store.get(live.token_hash) == live
