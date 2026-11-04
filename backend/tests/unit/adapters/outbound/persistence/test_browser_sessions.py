import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from docksight.adapters.outbound.persistence.browser_sessions import SQLiteBrowserSessions, revoke_obsolete_sessions
from docksight.adapters.outbound.persistence.database import PersistentDatabase, RecoveryReport
from docksight.application.browser_sessions import BrowserSessions, credential_fingerprints
from docksight.application.ports.browser_sessions import BrowserSession


async def test_session_survives_restart_with_only_hashes_at_rest(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    database = PersistentDatabase(path)
    await database.initialize_server()
    store = SQLiteBrowserSessions(database)
    credentials = {"alice": "secret-bearer-sentinel-at-least-24-characters"}
    issued = await BrowserSessions(store).login("alice", credential_fingerprints(credentials)["alice"])
    await database.close()
    persisted = await asyncio.to_thread(path.read_bytes)
    for secret in (credentials["alice"], issued.cookie, issued.principal.csrf_token, "provider-secret-sentinel"):
        assert secret.encode() not in persisted
    reopened = PersistentDatabase(path)
    await reopened.initialize_server()
    try:
        principal = await BrowserSessions(SQLiteBrowserSessions(reopened)).authenticate(issued.cookie, credentials)
        assert principal == issued.principal
    finally:
        await reopened.close()


async def test_sqlite_session_lifecycle_and_obsolete_revocation(tmp_path: Path) -> None:
    database = PersistentDatabase(tmp_path / "sessions.sqlite3")
    await database.initialize_server()
    store = SQLiteBrowserSessions(database)
    now = datetime(2026, 11, 4, tzinfo=UTC)
    try:
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
        await store.touch("a" * 64, now + timedelta(minutes=1))
        await store.touch("a" * 64, now)
        assert (record := await store.get("a" * 64)) is not None
        assert record.last_seen_at == now + timedelta(minutes=1)
        assert await store.get("missing") is None
        await store.revoke("missing", now)
        await store.touch("missing", now)
        assert await store.revoke_obsolete({"alice": "d" * 64, "bob": "e" * 64}, now) == 2
        assert await store.revoke_obsolete({"alice": "d" * 64}, now) == 0
        await store.revoke("a" * 64, now)
        await store.touch("a" * 64, now + timedelta(minutes=2))
        await store.revoke("a" * 64, now + timedelta(minutes=3))
        assert (record := await store.get("a" * 64)) is not None
        assert record.revoked_at == now and record.last_seen_at == now + timedelta(minutes=1)
    finally:
        await database.close()


async def test_startup_recovery_revokes_obsolete_credentials_inside_existing_transaction(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"
    database = PersistentDatabase(path)
    await database.initialize_server()
    old = {"alice": "alice-token-at-least-24-characters", "removed": "removed-token-at-least-24-characters"}
    sessions = BrowserSessions(SQLiteBrowserSessions(database))
    issued = [await sessions.login(actor, fingerprint) for actor, fingerprint in credential_fingerprints(old).items()]
    await database.close()
    now = datetime.now(UTC)

    def recover(session: Session) -> RecoveryReport:
        """Compose session revocation with the database's atomic startup recovery."""
        return RecoveryReport(revoked_sessions=revoke_obsolete_sessions(session, {"alice": "f" * 64}, now))

    reopened = PersistentDatabase(path, recoveries=[recover])
    try:
        report = await reopened.initialize_server()
        assert report.revoked_sessions == 2
        for session in issued:
            identity = hashlib.sha256(session.cookie.encode()).hexdigest()
            record = await SQLiteBrowserSessions(reopened).get(identity)
            assert record is not None and record.revoked_at == now
    finally:
        await reopened.close()
