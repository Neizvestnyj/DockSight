from collections.abc import Mapping
from datetime import datetime
from hmac import compare_digest

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from docksight.adapters.outbound.persistence.codec import utc_text
from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.adapters.outbound.persistence.rows import BrowserSessionRow
from docksight.application.ports.browser_sessions import MAX_CLEANUP_BATCH, BrowserSession, check_cleanup_limit


def revoke_obsolete_sessions(session: Session, fingerprints: Mapping[str, str], now: datetime) -> int:
    """Revoke obsolete authority inside the caller's startup recovery transaction."""
    revoked = 0
    for row in session.scalars(select(BrowserSessionRow).where(BrowserSessionRow.revoked_at.is_(None))):
        if not compare_digest(fingerprints.get(row.actor, ""), row.credential_fingerprint):
            row.revoked_at = utc_text(now)
            revoked += 1
    return revoked


def cleanup_browser_sessions(
    session: Session, now: datetime, idle_before: datetime, limit: int = MAX_CLEANUP_BATCH
) -> int:
    """Delete one stale-session batch inside an adapter transaction without deleting archive or action data."""
    check_cleanup_limit(limit)
    identities = session.scalars(
        select(BrowserSessionRow.token_hash)
        .where(
            or_(
                BrowserSessionRow.revoked_at.is_not(None),
                BrowserSessionRow.expires_at <= utc_text(now),
                BrowserSessionRow.last_seen_at <= utc_text(idle_before),
            )
        )
        .order_by(BrowserSessionRow.token_hash)
        .limit(limit)
    ).all()
    if identities:
        session.execute(delete(BrowserSessionRow).where(BrowserSessionRow.token_hash.in_(identities)))
    return len(identities)


class SQLiteBrowserSessions:
    """Persist only hashed authority in short transactions on the owned database thread."""

    def __init__(self, database: PersistentDatabase) -> None:
        """Share the explicitly opened database without owning its lifetime."""
        self._database = database

    async def add(self, record: BrowserSession) -> None:
        """Validate the owned record before inserting its secret-free relational fields."""
        record = BrowserSession.model_validate(record.model_dump())

        def insert(session: Session) -> None:
            """Insert a new lifecycle without persisting raw cookie or CSRF material."""
            session.add(
                BrowserSessionRow(
                    token_hash=record.token_hash,
                    actor=record.actor,
                    credential_fingerprint=record.credential_fingerprint,
                    created_at=utc_text(record.created_at),
                    last_seen_at=utc_text(record.last_seen_at),
                    expires_at=utc_text(record.expires_at),
                    revoked_at=utc_text(record.revoked_at) if record.revoked_at is not None else None,
                )
            )

        await self._database.transaction(insert, write=True)

    async def get(self, token_hash: str) -> BrowserSession | None:
        """Materialize a validated detached record with aware UTC timestamps."""

        def read(session: Session) -> BrowserSession | None:
            """Keep ORM references entirely within the short read transaction."""
            row = session.get(BrowserSessionRow, token_hash)
            if row is None:
                return None
            return BrowserSession.model_validate(
                {
                    "token_hash": row.token_hash,
                    "actor": row.actor,
                    "credential_fingerprint": row.credential_fingerprint,
                    "created_at": row.created_at,
                    "last_seen_at": row.last_seen_at,
                    "expires_at": row.expires_at,
                    "revoked_at": row.revoked_at,
                }
            )

        return await self._database.transaction(read)

    async def touch(self, token_hash: str, now: datetime) -> None:
        """Advance activity monotonically without reviving revoked or expired authority."""
        timestamp = utc_text(now)

        def update(session: Session) -> None:
            """Coalesce lifecycle advancement in the serial transaction owner."""
            row = session.get(BrowserSessionRow, token_hash)
            if row and row.revoked_at is None and row.last_seen_at < timestamp < row.expires_at:
                row.last_seen_at = timestamp

        await self._database.transaction(update, write=True)

    async def revoke(self, token_hash: str, now: datetime) -> None:
        """Retain the first revocation timestamp across repeated logout requests."""
        timestamp = utc_text(now)

        def update(session: Session) -> None:
            """Revoke at most one matching lifecycle without deleting history."""
            row = session.get(BrowserSessionRow, token_hash)
            if row and row.revoked_at is None:
                row.revoked_at = timestamp

        await self._database.transaction(update, write=True)

    async def revoke_obsolete(self, fingerprints: Mapping[str, str], now: datetime) -> int:
        """Invalidate removed actors and rotated credentials without retaining bearer values."""
        return await self._database.transaction(
            lambda session: revoke_obsolete_sessions(session, fingerprints, now), write=True
        )

    async def cleanup(self, now: datetime, idle_before: datetime, limit: int = MAX_CLEANUP_BATCH) -> int:
        """Commit at most 100 stale-session deletions or propagate the storage failure."""
        check_cleanup_limit(limit)
        return await self._database.transaction(
            lambda session: cleanup_browser_sessions(session, now, idle_before, limit), write=True
        )
