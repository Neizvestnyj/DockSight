from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from docksight.adapters.inbound.http.auth import (
    COOKIE_NAME,
    COOKIE_PATH,
    HttpAuthentication,
    Principal,
    bearer_principal,
    cookie_principal,
)
from docksight.adapters.inbound.http.schemas import BrowserSessionInput, BrowserSessionView
from docksight.application.browser_sessions import BrowserPrincipal, credential_fingerprints


def _view(principal: BrowserPrincipal) -> BrowserSessionView:
    """Project only the approved session bootstrap fields into the external contract."""
    return BrowserSessionView(actor=principal.actor, expires_at=principal.expires_at, csrf_token=principal.csrf_token)


def build_auth_router(auth: HttpAuthentication) -> APIRouter:
    """Bind first-party login, session bootstrap, and logout without bearer-only router dependencies."""
    router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])

    @router.post("/login")
    async def login(
        body: BrowserSessionInput,
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(bearer_principal)],
    ) -> BrowserSessionView:
        """Rotate any presented session after bearer and first-party transport validation."""
        issued = await auth.sessions.login(principal.actor, credential_fingerprints(auth.credentials)[principal.actor])
        await auth.sessions.logout(request.cookies.get(COOKIE_NAME, ""))
        response.set_cookie(
            COOKIE_NAME,
            issued.cookie,
            max_age=int(auth.sessions.ttl.total_seconds()),
            path=COOKIE_PATH,
            secure=auth.cookie_secure,
            httponly=True,
            samesite="lax",
        )
        return _view(issued.principal)

    @router.get("/session")
    async def session(principal: Annotated[BrowserPrincipal, Depends(cookie_principal)]) -> BrowserSessionView:
        """Restore only the selected cookie actor's expiry and in-memory CSRF authority."""
        return _view(principal)

    @router.post("/logout", status_code=204)
    async def logout(
        body: BrowserSessionInput,
        request: Request,
        principal: Annotated[BrowserPrincipal, Depends(cookie_principal)],
    ) -> Response:
        """Revoke this cookie after CSRF validation while preserving accepted work and history."""
        await auth.sessions.logout(request.cookies.get(COOKIE_NAME, ""))
        response = Response(status_code=204)
        response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, secure=auth.cookie_secure, httponly=True, samesite="lax")
        return response

    return router
