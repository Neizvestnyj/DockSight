from datetime import UTC, datetime, timedelta

from docksight.adapters.outbound.memory.browser_sessions import MemoryBrowserSessions
from docksight.application.ports.browser_sessions import BrowserSession


async def test_activity_cannot_revive_or_rewind_revoked_session() -> None:
    store = MemoryBrowserSessions()
    now = datetime(2026, 11, 4, tzinfo=UTC)
    record = BrowserSession(
        token_hash="a" * 64,
        actor="alice",
        credential_fingerprint="b" * 64,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=8),
    )
    await store.add(record)
    await store.touch(record.token_hash, now - timedelta(minutes=1))
    assert await store.get(record.token_hash) == record
    await store.revoke(record.token_hash, now)
    await store.touch(record.token_hash, now + timedelta(minutes=1))
    await store.revoke(record.token_hash, now + timedelta(minutes=2))
    revoked = await store.get(record.token_hash)
    assert revoked is not None and revoked.revoked_at == now and revoked.last_seen_at == now
    await store.touch("missing", now)
    await store.revoke("missing", now)


async def test_obsolete_credential_revocation_retains_matching_actor_and_first_timestamp() -> None:
    store = MemoryBrowserSessions()
    now = datetime(2026, 11, 4, tzinfo=UTC)
    for identity, actor in [("a", "alice"), ("b", "bob"), ("c", "removed")]:
        await store.add(
            BrowserSession(
                token_hash=identity * 64,
                actor=actor,
                credential_fingerprint="d" * 64,
                created_at=now,
                last_seen_at=now,
                expires_at=now + timedelta(hours=8),
            )
        )
    assert await store.revoke_obsolete({"alice": "d" * 64, "bob": "e" * 64}, now) == 2
    assert await store.revoke_obsolete({"alice": "d" * 64}, now + timedelta(minutes=1)) == 0
    assert (alice := await store.get("a" * 64)) is not None and alice.revoked_at is None
    assert (bob := await store.get("b" * 64)) is not None and bob.revoked_at == now
