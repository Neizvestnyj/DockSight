from collections.abc import Mapping
from dataclasses import dataclass
from hmac import compare_digest
from typing import Annotated, Final, cast

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer

from docksight.application.browser_sessions import BrowserPrincipal, BrowserSessionError, BrowserSessions

COOKIE_NAME: Final = "docksight_session"
COOKIE_PATH: Final = "/api/v1"
_SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})
_BEARER: Final = HTTPBearer(auto_error=False)
_COOKIE: Final = APIKeyCookie(name=COOKIE_NAME, scheme_name="BrowserCookie", auto_error=False)


class AuthenticationError(Exception):
    """Carry a safe authentication denial across middleware and route boundaries."""

    def __init__(self, code: str = "unauthorized", message: str = "Authentication required", status: int = 401) -> None:
        """Retain only public protocol details, never submitted credentials."""
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Principal:
    """Bind an actor to the explicitly selected authentication mechanism."""

    actor: str
    browser: BrowserPrincipal | None = None


def _resolved(request: Request) -> Principal:
    """Read the principal already selected once by the API middleware."""
    principal = cast(Principal | None, getattr(request.state, "principal", None))
    if principal is None:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    return principal


def authenticated_principal(
    request: Request,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Security(_BEARER)],
    cookie: Annotated[str | None, Security(_COOKIE)],
) -> Principal:
    """Share middleware identity while documenting bearer and cookie alternatives."""
    return _resolved(request)


def bearer_principal(
    request: Request, bearer: Annotated[HTTPAuthorizationCredentials | None, Security(_BEARER)]
) -> Principal:
    """Require explicit bearer selection for first-party browser login."""
    principal = _resolved(request)
    if principal.browser is not None:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    return principal


def cookie_principal(request: Request, cookie: Annotated[str | None, Security(_COOKIE)]) -> BrowserPrincipal:
    """Expose session-bound bootstrap data only after cookie authority was selected."""
    principal = _resolved(request)
    if principal.browser is None:
        raise HTTPException(401, "Browser session required")
    return principal.browser


class HttpAuthentication:
    """Resolve bearer-first authority and enforce first-party cookie transport boundaries."""

    def __init__(
        self,
        sessions: BrowserSessions,
        credentials: Mapping[str, str],
        *,
        browser_origin: str | None = None,
        cors_origins: tuple[str, ...] = (),
        cookie_secure: bool = True,
    ) -> None:
        """Bind validated deployment choices without consulting forwarded headers."""
        self.sessions, self.credentials = sessions, credentials
        self.browser_origin, self.cors_origins, self.cookie_secure = browser_origin, cors_origins, cookie_secure

    def _bearer(self, request: Request) -> Principal:
        """Compare every configured credential without a cookie fallback or position-dependent exit."""
        headers = request.headers.getlist("authorization")
        if len(headers) != 1:
            raise AuthenticationError()
        scheme, _, token = headers[0].partition(" ")
        matched: str | None = None
        for actor, expected in self.credentials.items():
            if compare_digest(token.encode(), expected.encode()):
                matched = actor
        if scheme.lower() != "bearer" or matched is None:
            raise AuthenticationError()
        return Principal(matched)

    def _origin(self, request: Request) -> str:
        """Use only the exact configured public origin or the direct request origin."""
        return self.browser_origin or f"{request.url.scheme}://{request.url.netloc}"

    def _check_browser_request(self, request: Request) -> None:
        """Reject cookie/login CSRF before any action or session mutation occurs."""
        if request.headers.get("origin") != self._origin(request):
            raise AuthenticationError("origin_not_allowed", "Origin is not allowed", 403)
        media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if media_type != "application/json" or request.headers.get("sec-fetch-site") == "cross-site":
            raise AuthenticationError("csrf_rejected", "Browser request is not allowed", 403)

    def _check_bearer_origin(self, request: Request) -> None:
        """Retain transient bearer access for explicitly allowed split-origin clients."""
        origin = request.headers.get("origin")
        if origin is not None and origin != self._origin(request) and origin not in self.cors_origins:
            raise AuthenticationError("origin_not_allowed", "Origin is not allowed", 403)

    async def resolve(self, request: Request) -> Principal:
        """Select explicit Authorization before cookie authority and validate the chosen transport."""
        login = request.url.path == "/api/v1/auth/login"
        if "authorization" in request.headers or login:
            principal = self._bearer(request)
            self._check_bearer_origin(request)
        else:
            principal = await self._browser(request)
        if login:
            self._check_browser_request(request)
            if self.cookie_secure and not self._origin(request).startswith("https://"):
                raise AuthenticationError("insecure_browser_origin", "Browser login requires HTTPS", 403)
        if request.url.path in {"/api/v1/auth/session", "/api/v1/auth/logout"} and principal.browser is None:
            raise AuthenticationError()
        request.state.principal, request.state.actor = principal, principal.actor
        return principal

    async def _browser(self, request: Request) -> Principal:
        """Check live session authority and require origin, JSON, and CSRF for unsafe methods."""
        try:
            browser = await self.sessions.authenticate(request.cookies.get(COOKIE_NAME, ""), self.credentials)
        except BrowserSessionError as error:
            raise AuthenticationError() from error
        if request.method not in _SAFE_METHODS:
            self._check_browser_request(request)
            submitted = request.headers.get("x-csrf-token", "")
            if not compare_digest(submitted.encode(), browser.csrf_token.encode()):
                raise AuthenticationError("csrf_rejected", "Browser request is not allowed", 403)
        elif request.headers.get("origin") not in {None, self._origin(request)}:
            raise AuthenticationError("origin_not_allowed", "Origin is not allowed", 403)
        return Principal(browser.actor, browser)
