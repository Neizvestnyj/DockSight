import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from docksight.adapters.outbound.persistence.actions import SQLiteActions
from docksight.adapters.outbound.persistence.browser_sessions import (
    SQLiteBrowserSessions,
    cleanup_browser_sessions,
    revoke_obsolete_sessions,
)
from docksight.adapters.outbound.persistence.codec import utc_text
from docksight.adapters.outbound.persistence.database import PersistentDatabase, RecoveryReport
from docksight.adapters.outbound.persistence.investigations import SQLiteInvestigations
from docksight.adapters.outbound.persistence.rows import (
    ActionAuditRow,
    InvestigationRow,
    PreparedActionRow,
    SubmissionReceiptRow,
    TargetGuardRow,
)
from docksight.application.browser_sessions import BrowserSessions, credential_fingerprints
from docksight.application.investigations.errors import StorageError
from docksight.application.ports.browser_sessions import BrowserSession
from docksight.domain.actions import PreparedAction
from tests.browser_sessions import assert_bounded_browser_session_cleanup


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


async def test_bounded_cleanup_removes_only_expired_and_revoked_sessions(tmp_path: Path) -> None:
    database = PersistentDatabase(tmp_path / "sessions.sqlite3")
    await database.initialize_server()
    try:
        now, investigation_id = datetime.now(UTC), str(uuid4())
        await SQLiteInvestigations(database).create("alice", investigation_id, "local", now)
        actions = SQLiteActions(database)
        action = PreparedAction(
            str(uuid4()), "alice", "local", "a" * 64, "restart", "fingerprint", now + timedelta(minutes=5)
        )
        await actions.add(action, now)
        await actions.claim(action.id, "alice", "original-idempotency-key", True, now)

        def seed_receipt(session: Session) -> None:
            """Retain duplicate protection independently of browser authority."""
            session.add(
                SubmissionReceiptRow(
                    actor="alice",
                    submission_id=str(uuid4()),
                    input_digest="a" * 64,
                    turn_id=str(uuid4()),
                    investigation_id=investigation_id,
                    accepted_at=utc_text(now),
                )
            )

        def protected_rows(session: Session) -> dict[str, list[tuple[object, ...]]]:
            """Compare full retained rows including action idempotency, audit, guards, and history."""
            tables = (InvestigationRow, PreparedActionRow, SubmissionReceiptRow, ActionAuditRow, TargetGuardRow)
            return {
                row.__tablename__: [tuple(item) for item in session.execute(select(row.__table__))] for row in tables
            }

        await database.transaction(seed_receipt, write=True)
        before = await database.transaction(protected_rows)
        assert all(before.values())
        await assert_bounded_browser_session_cleanup(SQLiteBrowserSessions(database))
        assert await database.transaction(protected_rows) == before
    finally:
        await database.close()


async def test_cleanup_failure_rolls_back_session_deletion_and_closes_write_admission(tmp_path: Path) -> None:
    database = PersistentDatabase(tmp_path / "sessions.sqlite3")
    await database.initialize_server()
    store = SQLiteBrowserSessions(database)
    now = datetime.now(UTC)
    records = [
        BrowserSession(
            token_hash=identity * 64,
            actor="alice",
            credential_fingerprint="d" * 64,
            created_at=now - timedelta(hours=2),
            last_seen_at=now - timedelta(hours=1),
            expires_at=now,
        )
        for identity in ("a", "b")
    ]
    try:
        for record in records:
            await store.add(record)

        def fail_deletion(session: Session) -> None:
            """Make a real SQLite write fail after the cleanup statement has selected its batch."""
            session.execute(
                text(
                    "CREATE TRIGGER fail_cleanup BEFORE DELETE ON browser_sessions "
                    "WHEN OLD.token_hash = '" + "b" * 64 + "' "
                    "BEGIN SELECT RAISE(ABORT, 'cleanup write failed'); END"
                )
            )

        await database.transaction(fail_deletion, write=True)
        with pytest.raises(StorageError):
            await BrowserSessions(store, clock=lambda: now).cleanup()
        assert not database.healthy
        assert [await store.get(record.token_hash) for record in records] == records
        with pytest.raises(StorageError):
            await store.cleanup(now, now - timedelta(hours=1))
    finally:
        await database.close()


async def test_cleanup_composes_with_startup_recovery_and_rolls_back_as_one_transaction(tmp_path: Path) -> None:
    path, now = tmp_path / "sessions.sqlite3", datetime.now(UTC)
    database = PersistentDatabase(path)
    await database.initialize_server()
    record = BrowserSession(
        token_hash="a" * 64,
        actor="alice",
        credential_fingerprint="d" * 64,
        created_at=now - timedelta(hours=2),
        last_seen_at=now,
        expires_at=now,
    )
    try:
        await SQLiteBrowserSessions(database).add(record)
    finally:
        await database.close()

    def failing_recovery(session: Session) -> RecoveryReport:
        """Abort after deleting a session so the entire startup transaction must roll back."""
        assert cleanup_browser_sessions(session, now, now - timedelta(hours=1)) == 1
        raise OSError("Recovery failed after session cleanup")

    failed = PersistentDatabase(path, recoveries=[failing_recovery])
    try:
        with pytest.raises(StorageError):
            await failed.initialize_server()
        assert not failed.healthy
    finally:
        await failed.close()

    def successful_recovery(session: Session) -> RecoveryReport:
        """Find the retained row again after rollback and commit only this requested batch."""
        assert cleanup_browser_sessions(session, now, now - timedelta(hours=1)) == 1
        return RecoveryReport()

    reopened = PersistentDatabase(path, recoveries=[successful_recovery])
    try:
        await reopened.initialize_server()
        assert await SQLiteBrowserSessions(reopened).get(record.token_hash) is None
    finally:
        await reopened.close()
