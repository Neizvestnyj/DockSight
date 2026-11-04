import base64
import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from docksight.adapters.outbound.memory.browser_sessions import MemoryBrowserSessions
from docksight.application.browser_sessions import BrowserSessionError, BrowserSessions, credential_fingerprints

NOW = datetime(2026, 11, 4, tzinfo=UTC)
TOKEN = "alice-api-token-at-least-24-characters"
CREDENTIALS = {"alice": TOKEN}


class Clock:
    """Expose controllable aware time without waiting for session boundaries."""

    def __init__(self) -> None:
        """Begin at the deterministic session creation instant."""
        self.now = NOW

    def __call__(self) -> datetime:
        """Return the current test instant."""
        return self.now


async def test_login_hashes_cookie_and_binds_current_actor_credential() -> None:
    store = MemoryBrowserSessions()
    sessions = BrowserSessions(store, clock=Clock())
    fingerprint = hashlib.sha256(("alice\0" + TOKEN).encode()).hexdigest()
    issued = await sessions.login("alice", fingerprint)
    assert len(base64.urlsafe_b64decode(issued.cookie + "=")) == 32
    stored = await store.get(hashlib.sha256(issued.cookie.encode()).hexdigest())
    assert stored is not None
    assert stored.actor == "alice"
    assert stored.credential_fingerprint == fingerprint
    assert stored.expires_at == NOW + timedelta(hours=8)
    assert issued.cookie not in stored.model_dump_json()
    assert TOKEN not in stored.model_dump_json()
    assert issued.principal.csrf_token not in stored.model_dump_json()
    assert credential_fingerprints(CREDENTIALS) == {"alice": fingerprint}
    assert (await sessions.authenticate(issued.cookie, CREDENTIALS)).actor == "alice"


async def test_last_seen_is_coalesced_and_idle_expiry_is_inclusive() -> None:
    clock, store = Clock(), MemoryBrowserSessions()
    sessions = BrowserSessions(store, clock=clock)
    issued = await sessions.login("alice", credential_fingerprints(CREDENTIALS)["alice"])
    identity = hashlib.sha256(issued.cookie.encode()).hexdigest()
    clock.now += timedelta(seconds=59)
    await sessions.authenticate(issued.cookie, CREDENTIALS)
    record = await store.get(identity)
    assert record is not None and record.last_seen_at == NOW
    clock.now += timedelta(seconds=1)
    await sessions.authenticate(issued.cookie, CREDENTIALS)
    record = await store.get(identity)
    assert record is not None and record.last_seen_at == NOW + timedelta(minutes=1)
    clock.now += timedelta(hours=1)
    with pytest.raises(BrowserSessionError):
        await sessions.authenticate(issued.cookie, CREDENTIALS)


async def test_absolute_expiry_is_never_extended_by_activity() -> None:
    clock = Clock()
    sessions = BrowserSessions(MemoryBrowserSessions(), clock=clock)
    issued = await sessions.login("alice", credential_fingerprints(CREDENTIALS)["alice"])
    for minute in range(30, 480, 30):
        clock.now = NOW + timedelta(minutes=minute)
        principal = await sessions.authenticate(issued.cookie, CREDENTIALS)
        assert principal.expires_at == NOW + timedelta(hours=8)
    clock.now = NOW + timedelta(hours=8)
    with pytest.raises(BrowserSessionError):
        await sessions.authenticate(issued.cookie, CREDENTIALS)


@pytest.mark.parametrize("credentials", [{}, {"alice": "replacement-token-at-least-24-characters"}])
async def test_actor_removal_and_rotation_invalidate_session(credentials: dict[str, str]) -> None:
    sessions = BrowserSessions(MemoryBrowserSessions(), clock=Clock())
    issued = await sessions.login("alice", credential_fingerprints(CREDENTIALS)["alice"])
    with pytest.raises(BrowserSessionError):
        await sessions.authenticate(issued.cookie, credentials)


async def test_logout_is_idempotent_and_unknown_or_malformed_cookies_are_unauthorized() -> None:
    sessions = BrowserSessions(MemoryBrowserSessions(), clock=Clock())
    issued = await sessions.login("alice", credential_fingerprints(CREDENTIALS)["alice"])
    await sessions.logout(issued.cookie)
    await sessions.logout(issued.cookie)
    for cookie in (issued.cookie, "", "a" * 43, "!" * 43, "a" * 20000):
        with pytest.raises(BrowserSessionError):
            await sessions.authenticate(cookie, CREDENTIALS)
    await sessions.logout("malformed")
