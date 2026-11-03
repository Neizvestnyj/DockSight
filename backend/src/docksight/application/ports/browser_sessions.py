from datetime import datetime
from typing import Annotated, Protocol

from pydantic import AwareDatetime, Field

from docksight.application.investigations.contracts import FrozenContract, Label

type TokenHash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


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

    async def add(self, session: BrowserSession) -> None:
        """Retain a new hashed session with its configured credential fingerprint."""
        ...

    async def get(self, token_hash: str, now: datetime) -> BrowserSession:
        """Read an active session without returning any raw token."""
        ...

    async def touch(self, token_hash: str, now: datetime) -> BrowserSession:
        """Advance last-seen time without extending absolute expiry."""
        ...

    async def revoke(self, token_hash: str, now: datetime) -> None:
        """Revoke one session idempotently."""
        ...

    async def cleanup(self, now: datetime, limit: int = 100) -> int:
        """Remove at most one bounded batch of expired or revoked sessions."""
        ...
