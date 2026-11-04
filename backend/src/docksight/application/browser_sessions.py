import base64
import binascii
import hashlib
import hmac
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from docksight.application.ports.browser_sessions import BrowserSession, BrowserSessionStore

_TOUCH_INTERVAL: Final = timedelta(minutes=1)
_CSRF_MESSAGE: Final = b"docksight-csrf-v1"


class BrowserSessionError(Exception):
    """Reject absent, expired, revoked, or obsolete browser authority without disclosing its cause."""

    def __init__(self) -> None:
        """Expose only a safe authentication failure."""
        super().__init__("Authentication required")


@dataclass(frozen=True)
class BrowserPrincipal:
    """Describe authenticated browser authority with an in-memory-only derived CSRF value."""

    actor: str
    expires_at: datetime
    csrf_token: str = field(repr=False)


@dataclass(frozen=True)
class IssuedBrowserSession:
    """Transfer a newly generated cookie only to the transport that issues it."""

    cookie: str = field(repr=False)
    principal: BrowserPrincipal


def credential_fingerprints(credentials: Mapping[str, str]) -> dict[str, str]:
    """Bind stable actor names to current bearer values without retaining those values."""
    return {actor: hashlib.sha256(f"{actor}\0{token}".encode()).hexdigest() for actor, token in credentials.items()}


def _now() -> datetime:
    """Read aware UTC time for lifecycle comparisons."""
    return datetime.now(UTC)


def _encoded(value: bytes) -> str:
    """Encode random or derived bytes in canonical unpadded base64url form."""
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decoded(cookie: str) -> bytes:
    """Reject malformed and noncanonical cookies before hashing or deriving CSRF."""
    if len(cookie) != 43:
        raise BrowserSessionError()
    try:
        raw = base64.b64decode(cookie + "=", altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as error:
        raise BrowserSessionError() from error
    if len(raw) != 32 or _encoded(raw) != cookie:
        raise BrowserSessionError()
    return raw


def _identity(cookie: str) -> str:
    """Address stored lifecycle records without persisting cookie material."""
    return hashlib.sha256(cookie.encode("ascii")).hexdigest()


def _principal(record: BrowserSession, raw: bytes) -> BrowserPrincipal:
    """Derive CSRF authority afresh from the decoded cookie key."""
    return BrowserPrincipal(record.actor, record.expires_at, _encoded(hmac.digest(raw, _CSRF_MESSAGE, "sha256")))


class BrowserSessions:
    """Issue opaque browser credentials and enforce absolute, idle, and configuration lifetimes."""

    def __init__(
        self,
        store: BrowserSessionStore,
        ttl: int = 28800,
        idle_ttl: int = 3600,
        *,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        """Bind transport-independent storage and an injectable aware clock."""
        self.store = store
        self.ttl = timedelta(seconds=ttl)
        self.idle_ttl = timedelta(seconds=idle_ttl)
        self._clock = clock

    async def login(self, actor: str, credential_fingerprint: str) -> IssuedBrowserSession:
        """Persist only a hash of 32 random bytes before issuing their browser credential."""
        raw = secrets.token_bytes(32)
        cookie, now = _encoded(raw), self._clock()
        record = BrowserSession(
            token_hash=_identity(cookie),
            actor=actor,
            credential_fingerprint=credential_fingerprint,
            created_at=now,
            last_seen_at=now,
            expires_at=now + self.ttl,
        )
        await self.store.add(record)
        return IssuedBrowserSession(cookie, _principal(record, raw))

    async def authenticate(self, cookie: str, current_credentials: Mapping[str, str]) -> BrowserPrincipal:
        """Check live configured authority on every request and coalesce last-seen writes."""
        raw = _decoded(cookie)
        identity, now = _identity(cookie), self._clock()
        record = await self.store.get(identity)
        if record is None or record.revoked_at is not None:
            raise BrowserSessionError()
        expected = credential_fingerprints(current_credentials).get(record.actor, "")
        if not hmac.compare_digest(expected, record.credential_fingerprint):
            await self.store.revoke(identity, now)
            raise BrowserSessionError()
        if now >= record.expires_at or now >= record.last_seen_at + self.idle_ttl:
            raise BrowserSessionError()
        if now - record.last_seen_at >= _TOUCH_INTERVAL:
            await self.store.touch(identity, now)
        return _principal(record, raw)

    async def logout(self, cookie: str) -> None:
        """Revoke a presented session idempotently while tolerating malformed stale cookies."""
        try:
            _decoded(cookie)
        except BrowserSessionError:
            return
        await self.store.revoke(_identity(cookie), self._clock())
