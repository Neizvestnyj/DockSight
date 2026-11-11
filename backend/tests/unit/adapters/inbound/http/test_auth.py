from typing import cast

import pytest
from fastapi import HTTPException, Request

from docksight.adapters.inbound.http.auth import (
    HttpAuthentication,
    Principal,
    authenticated_principal,
    bearer_principal,
    cookie_principal,
)
from docksight.adapters.outbound.memory.browser_sessions import MemoryBrowserSessions
from docksight.application.browser_sessions import BrowserSessions, credential_fingerprints


def auth_request(headers: list[tuple[bytes, bytes]]) -> Request:
    """Build a direct HTTPS API request with no framework middleware identity."""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "server": ("example.test", 443),
            "path": "/api/v1/hosts",
            "query_string": b"",
            "headers": headers,
        }
    )


def test_security_dependencies_fail_closed_without_middleware_principal() -> None:
    request = auth_request([])
    with pytest.raises(HTTPException) as error:
        authenticated_principal(request, None, None)
    assert error.value.status_code == 401


async def test_security_dependencies_share_selected_mechanism_without_reinterpreting_cookie() -> None:
    credentials = {"alice": "alice-secret-at-least-24-characters"}
    sessions = BrowserSessions(MemoryBrowserSessions())
    issued = await sessions.login("alice", credential_fingerprints(credentials)["alice"])
    request = auth_request([(b"cookie", f"docksight_session={issued.cookie}".encode())])
    auth = HttpAuthentication(sessions, credentials)
    selected = await auth.resolve(request)
    assert authenticated_principal(request, None, issued.cookie) is selected
    assert cookie_principal(request, issued.cookie) == issued.principal
    with pytest.raises(HTTPException):
        bearer_principal(request, None)
    request = auth_request(
        [
            (b"authorization", f"Bearer {credentials['alice']}".encode()),
            (b"cookie", f"docksight_session={issued.cookie}".encode()),
        ]
    )
    selected = await auth.resolve(request)
    assert bearer_principal(request, None) is selected
    assert cast(Principal, request.state.principal).browser is None
    with pytest.raises(HTTPException):
        cookie_principal(request, issued.cookie)
