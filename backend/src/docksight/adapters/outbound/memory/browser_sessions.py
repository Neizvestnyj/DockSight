from collections.abc import Mapping
from datetime import datetime
from hmac import compare_digest

from docksight.application.ports.browser_sessions import BrowserSession


class MemoryBrowserSessions:
    """Retain hash-only browser lifecycle records for explicit in-memory wiring."""

    def __init__(self) -> None:
        """Start an isolated session registry without durable restart guarantees."""
        self._records: dict[str, BrowserSession] = {}

    async def add(self, record: BrowserSession) -> None:
        """Insert a new immutable hash-only lifecycle record."""
        self._records[record.token_hash] = record

    async def get(self, token_hash: str) -> BrowserSession | None:
        """Return immutable lifecycle data without changing authentication state."""
        return self._records.get(token_hash)

    async def touch(self, token_hash: str, now: datetime) -> None:
        """Advance activity monotonically without reviving revoked or expired sessions."""
        record = self._records.get(token_hash)
        if record and record.revoked_at is None and record.last_seen_at < now < record.expires_at:
            self._records[token_hash] = record.model_copy(update={"last_seen_at": now})

    async def revoke(self, token_hash: str, now: datetime) -> None:
        """Retain the first revocation timestamp even across repeated logout requests."""
        record = self._records.get(token_hash)
        if record and record.revoked_at is None:
            self._records[token_hash] = record.model_copy(update={"revoked_at": now})

    async def revoke_obsolete(self, fingerprints: Mapping[str, str], now: datetime) -> int:
        """Invalidate removed actors and rotated credentials without deleting owned history."""
        obsolete = [
            identity
            for identity, record in self._records.items()
            if record.revoked_at is None
            and not compare_digest(fingerprints.get(record.actor, ""), record.credential_fingerprint)
        ]
        for identity in obsolete:
            await self.revoke(identity, now)
        return len(obsolete)
