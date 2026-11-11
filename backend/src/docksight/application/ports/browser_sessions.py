from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Final, Protocol

from pydantic import AwareDatetime, Field

from docksight.application.investigations.contracts import FrozenContract, Label

type TokenHash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
MAX_CLEANUP_BATCH: Final = 100


def check_cleanup_limit(limit: int) -> None:
    """Reject browser-session maintenance requests outside one bounded batch."""
    if not 1 <= limit <= MAX_CLEANUP_BATCH:
        raise ValueError("Browser session cleanup limit must be between 1 and 100")


class BrowserSession(FrozenContract):
    """Own a hashed session identity and absolute/idle lifecycle without raw credentials."""

    token_hash: TokenHash
    actor: Label
    credential_fingerprint: TokenHash
    created_at: AwareDatetime
    last_seen_at: AwareDatetime
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None = None


class BrowserSessionStore(Protocol):
    """Persist browser lifecycle independently of HTTP cookies and authentication parsing."""

    async def add(self, record: BrowserSession) -> None:
        """Retain a new hashed session with its configured credential fingerprint."""
        ...

    async def get(self, token_hash: str) -> BrowserSession | None:
        """Read detached lifecycle data without returning any raw token."""
        ...

    async def touch(self, token_hash: str, now: datetime) -> None:
        """Advance last-seen time without extending absolute expiry."""
        ...

    async def revoke(self, token_hash: str, now: datetime) -> None:
        """Revoke one session idempotently."""
        ...

    async def revoke_obsolete(self, fingerprints: Mapping[str, str], now: datetime) -> int:
        """Revoke sessions whose stable actor or configured credential no longer matches."""
        ...

    async def cleanup(self, now: datetime, idle_before: datetime, limit: int = MAX_CLEANUP_BATCH) -> int:
        """Delete at most 100 revoked, absolutely expired, or idle-expired session records only."""
        ...
