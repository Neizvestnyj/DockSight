import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from docksight.adapters.outbound.memory.browser_sessions import MemoryBrowserSessions
from docksight.adapters.outbound.persistence.browser_sessions import SQLiteBrowserSessions
from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.application.ports.browser_sessions import BrowserSession, BrowserSessionStore
from docksight.bootstrap import Settings, build_components
from docksight.main import create_app
from tests.fakes import FakeRuntime, ScriptedModel

TOKEN = "browser-login-token-at-least-24-characters"
BOB = "bob-browser-token-at-least-24-characters"
ORIGIN = "https://docksight.example"
BEARER = {"Authorization": f"Bearer {TOKEN}"}
LOGIN = {**BEARER, "Origin": ORIGIN}


def browser_client(*, browser_session_store: BrowserSessionStore | None = None, **overrides: object) -> TestClient:
    """Build an isolated first-party API without opening the operator's state database."""
    settings = Settings.model_validate(
        {
            "state_backend": "memory",
            "api_token": TOKEN,
            "api_tokens": {"bob": BOB},
            "browser_origin": ORIGIN,
            "cookie_secure": True,
            **overrides,
        }
    )
    runtime = FakeRuntime()
    components = build_components(
        settings, reader=runtime, writer=runtime, model=ScriptedModel([]), browser_session_store=browser_session_store
    )
    return TestClient(create_app(settings, components), base_url=ORIGIN)


@pytest.mark.parametrize("local_cookie_secure", ["true", "false"])
def test_login_restores_cookie_session_rotates_and_logs_out(
    monkeypatch: pytest.MonkeyPatch, local_cookie_secure: str
) -> None:
    """Keep the HTTPS fixture secure when the developer uses loopback HTTP cookies locally."""
    monkeypatch.setenv("DOCKSIGHT_COOKIE_SECURE", local_cookie_secure)
    with browser_client() as api:
        response = api.post("/api/v1/auth/login", headers=LOGIN, json={})
        assert response.status_code == 200
        cookie = api.cookies["docksight_session"]
        raw = base64.urlsafe_b64decode(cookie + "=")
        assert len(raw) == 32
        expected_csrf = base64.urlsafe_b64encode(hmac.digest(raw, b"docksight-csrf-v1", "sha256")).decode().rstrip("=")
        assert response.json()["csrf_token"] == expected_csrf
        assert response.json()["actor"] == "operator"
        attributes = response.headers["set-cookie"]
        for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/api/v1", "Max-Age=28800"):
            assert attribute in attributes
        assert "Domain=" not in attributes
        assert api.get("/api/v1/hosts").status_code == 200
        assert api.get("/api/v1/auth/session").json() == response.json()
        rotated = api.post("/api/v1/auth/login", headers=LOGIN, json={})
        assert api.cookies["docksight_session"] != cookie
        stale = api.get("/api/v1/hosts", headers={"Cookie": f"docksight_session={cookie}"})
        assert stale.status_code == 401
        csrf = rotated.json()["csrf_token"]
        logged_out = api.post("/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}, json={})
        assert logged_out.status_code == 204
        assert "Max-Age=0" in logged_out.headers["set-cookie"]
        assert api.get("/api/v1/auth/session").status_code == 401
        for result in (response, rotated, logged_out, stale):
            assert result.headers["cache-control"] == "no-store"


async def test_browser_login_reclaims_one_bounded_stale_session_batch() -> None:
    now, store = datetime.now(UTC), MemoryBrowserSessions()
    for index in range(105):
        await store.add(
            BrowserSession(
                token_hash=f"{index:064x}",
                actor="operator",
                credential_fingerprint="b" * 64,
                created_at=now - timedelta(hours=2),
                last_seen_at=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
            )
        )
    with browser_client(browser_session_store=store) as api:
        assert api.post("/api/v1/auth/login", headers=LOGIN, json={}).status_code == 200
        assert await store.cleanup(now, now - timedelta(hours=1), 100) == 5
        assert api.get("/api/v1/auth/session").status_code == 200


@pytest.mark.parametrize("origin", [None, "null", "https://foreign.example"])
def test_login_rejects_missing_null_and_foreign_origins(origin: str | None) -> None:
    with browser_client(cors_origins=("https://foreign.example",)) as api:
        headers = {**BEARER, **({"Origin": origin} if origin is not None else {})}
        response = api.post("/api/v1/auth/login", headers=headers, json={})
        assert response.status_code == 403
        assert "set-cookie" not in response.headers
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("origin", "csrf", "content_type", "fetch_site"),
    [
        (None, "valid", "application/json", None),
        ("null", "valid", "application/json", None),
        ("https://foreign.example", "valid", "application/json", None),
        (ORIGIN, None, "application/json", None),
        (ORIGIN, "wrong", "application/json", None),
        (ORIGIN, "valid", "text/plain", None),
        (ORIGIN, "valid", "application/json", "cross-site"),
    ],
)
def test_cookie_unsafe_requests_require_exact_origin_json_and_csrf(
    origin: str | None, csrf: str | None, content_type: str, fetch_site: str | None
) -> None:
    with browser_client() as api:
        login = api.post("/api/v1/auth/login", headers=LOGIN, json={}).json()
        headers = {"Content-Type": content_type}
        if origin is not None:
            headers["Origin"] = origin
        if csrf is not None:
            headers["X-CSRF-Token"] = login["csrf_token"] if csrf == "valid" else csrf
        if fetch_site is not None:
            headers["Sec-Fetch-Site"] = fetch_site
        assert api.post("/api/v1/actions", headers=headers, content="{}").status_code == 403
        assert api.post("/api/v1/auth/logout", headers=headers, content="{}").status_code == 403
        assert api.get("/api/v1/auth/session").status_code == 200


@pytest.mark.parametrize("authorization", ["Bearer wrong", "Basic abc", "", "Bearer"])
def test_explicit_invalid_authorization_never_falls_back_to_cookie(authorization: str) -> None:
    with browser_client() as api:
        api.post("/api/v1/auth/login", headers=LOGIN, json={})
        for path in ("/hosts", "/auth/session"):
            assert api.get("/api/v1" + path, headers={"Authorization": authorization}).status_code == 401


def test_valid_bearer_selects_its_actor_without_exposing_other_cookie_state() -> None:
    with browser_client(cors_origins=("https://remote.example",)) as api:
        api.post("/api/v1/auth/login", headers=LOGIN, json={})
        bob = {"Authorization": f"Bearer {BOB}"}
        prepared = api.post(
            "/api/v1/actions", headers=bob, json={"host": "local", "container_id": "a" * 64, "operation": "restart"}
        )
        assert prepared.status_code == 201
        path = "/api/v1/actions/" + prepared.json()["id"]
        assert api.get(path, headers=bob).status_code == 200
        assert api.get(path).status_code == 404
        for path in ("/api/v1/auth/session", "/api/v1/auth/logout"):
            response = api.get(path, headers=bob) if path.endswith("session") else api.post(path, headers=bob, json={})
            assert response.status_code == 401
            assert "csrf_token" not in response.text
            assert "set-cookie" not in response.headers
        assert api.get("/api/v1/auth/session").status_code == 200
        remote = api.get("/api/v1/hosts", headers={**bob, "Origin": "https://remote.example"})
        assert remote.status_code == 200
        assert remote.headers["access-control-allow-origin"] == "https://remote.example"


@pytest.mark.parametrize("headers", [{"Content-Type": "text/plain"}, {"Sec-Fetch-Site": "cross-site"}])
def test_login_rejects_non_json_and_cross_site_fetch(headers: dict[str, str]) -> None:
    with browser_client() as api:
        response = api.post("/api/v1/auth/login", headers={**LOGIN, **headers}, content="{}")
        assert response.status_code == 403


def test_cookie_proxy_requires_configured_origin_and_ignores_forwarded_headers() -> None:
    settings = Settings(state_backend="memory", api_token=TOKEN, _env_file=None)
    runtime = FakeRuntime()
    components = build_components(settings, reader=runtime, writer=runtime, model=ScriptedModel([]))
    with TestClient(create_app(settings, components), base_url="http://backend:8000") as api:
        response = api.post(
            "/api/v1/auth/login",
            headers={**LOGIN, "X-Forwarded-Proto": "https", "X-Forwarded-Host": "docksight.example"},
            json={},
        )
        assert response.status_code == 403
    with browser_client(browser_origin="http://127.0.0.1:4173", cookie_secure=False) as api:
        response = api.post("/api/v1/auth/login", headers={**BEARER, "Origin": "http://127.0.0.1:4173"}, json={})
        assert response.status_code == 200
        assert "Secure" not in response.headers["set-cookie"]


def test_preflight_and_openapi_describe_alternative_credentials() -> None:
    with browser_client(cors_origins=("https://remote.example",)) as api:
        response = api.options(
            "/api/v1/investigations/example",
            headers={
                "Origin": "https://remote.example",
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "authorization,content-type,x-csrf-token",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-credentials" not in response.headers
        document = api.get("/openapi.json").json()
        assert document["paths"]["/api/v1/hosts"]["get"]["security"] == [{"HTTPBearer": []}, {"BrowserCookie": []}]
        assert document["paths"]["/api/v1/auth/login"]["post"]["security"] == [{"HTTPBearer": []}]
        assert document["paths"]["/api/v1/auth/session"]["get"]["security"] == [{"BrowserCookie": []}]


def test_login_and_errors_do_not_log_submitted_secrets(caplog: pytest.LogCaptureFixture) -> None:
    """Captured application logs must never retain submitted bearer, cookie, or provider credentials."""
    with browser_client(model_api_key="provider-secret-sentinel-123456") as api:
        response = api.post("/api/v1/auth/login", headers=LOGIN, json={})
        assert response.status_code == 200
        cookie = api.cookies["docksight_session"]
        api.post("/api/v1/actions", headers={"Origin": ORIGIN, "X-CSRF-Token": "csrf-secret-sentinel"}, json={})
        for secret in (TOKEN, BOB, cookie, "provider-secret-sentinel-123456", "csrf-secret-sentinel"):
            assert secret not in caplog.text
        assert hashlib.sha256(cookie.encode()).hexdigest() != cookie


@pytest.mark.parametrize("origin", [None, "http://example.com", "https://localhost", "http://localhost:4173/path"])
def test_insecure_cookie_requires_explicit_loopback_http_origin(origin: str | None) -> None:
    with pytest.raises(ValidationError):
        Settings(state_backend="memory", api_token=TOKEN, browser_origin=origin, cookie_secure=False, _env_file=None)


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.com/path",
        "https://user@example.com",
        "null",
        "https://example.com?query=value",
        "https://example.com#fragment",
    ],
)
def test_browser_origin_must_be_exact_origin(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(state_backend="memory", api_token=TOKEN, browser_origin=origin, _env_file=None)


def test_cookie_authorized_action_uses_session_actor_and_bearer_login_is_required() -> None:
    with browser_client() as api:
        assert api.post("/api/v1/auth/login", headers={"Origin": ORIGIN}, json={}).status_code == 401
        login = api.post("/api/v1/auth/login", headers=LOGIN, json={})
        csrf = login.json()["csrf_token"]
        login_without_bearer = api.post("/api/v1/auth/login", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}, json={})
        assert login_without_bearer.status_code == 401
        prepared = api.post(
            "/api/v1/actions",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={"host": "local", "container_id": "a" * 64, "operation": "restart"},
        )
        assert prepared.status_code == 201
        assert api.get("/api/v1/actions/" + prepared.json()["id"]).status_code == 200


def test_allowed_bearer_origin_receives_cors_headers_on_auth_errors() -> None:
    with browser_client(cors_origins=("https://remote.example",)) as api:
        response = api.get("/api/v1/hosts", headers={"Origin": "https://remote.example", "Authorization": "Bearer bad"})
        assert response.status_code == 401
        assert response.headers["access-control-allow-origin"] == "https://remote.example"
        assert response.headers["cache-control"] == "no-store"


async def test_persisted_http_login_restores_and_rejects_rotated_actor_tokens(tmp_path: Path) -> None:
    """Actual browser login persists no submitted secret and reloads current credential authority."""
    path = tmp_path / "http-sessions.sqlite3"
    database = PersistentDatabase(path)
    await database.initialize_server()
    try:
        with browser_client(
            browser_session_store=SQLiteBrowserSessions(database), model_api_key="provider-sentinel"
        ) as api:
            response = api.post("/api/v1/auth/login", headers=LOGIN, json={})
            assert response.status_code == 200
            cookie, session = api.cookies["docksight_session"], response.json()
    finally:
        await database.close()
    for secret in (TOKEN, BOB, cookie, session["csrf_token"], "provider-sentinel"):
        assert secret.encode() not in path.read_bytes()
    reopened = PersistentDatabase(path)
    await reopened.initialize_server()
    try:
        with browser_client(browser_session_store=SQLiteBrowserSessions(reopened)) as api:
            api.cookies.set("docksight_session", cookie)
            assert api.get("/api/v1/auth/session").json() == session
        with browser_client(
            browser_session_store=SQLiteBrowserSessions(reopened),
            api_token="replacement-operator-token-at-least-24-characters",
        ) as api:
            api.cookies.set("docksight_session", cookie)
            assert api.get("/api/v1/auth/session").status_code == 401
        with browser_client(browser_session_store=SQLiteBrowserSessions(reopened)) as api:
            api.cookies.set("docksight_session", cookie)
            assert api.get("/api/v1/auth/session").status_code == 401
    finally:
        await reopened.close()


async def test_storage_failure_never_issues_cookie_or_falls_back_to_memory(tmp_path: Path) -> None:
    database = PersistentDatabase(tmp_path / "sessions.sqlite3")
    await database.initialize_server()
    with browser_client(browser_session_store=SQLiteBrowserSessions(database), cors_origins=(ORIGIN,)) as api:
        issued = api.post("/api/v1/auth/login", headers=LOGIN, json={})
        assert issued.status_code == 200
        await database.close()
        for response in (
            api.get("/api/v1/auth/session", headers={"Origin": ORIGIN}),
            api.post("/api/v1/auth/login", headers=LOGIN, json={}),
        ):
            assert response.status_code == 503
            assert response.json()["code"] == "storage_unavailable"
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["access-control-allow-origin"] == ORIGIN
            assert "set-cookie" not in response.headers


@pytest.mark.parametrize("origin", ["http://localhost:4173", "http://127.0.0.1:5173", "http://[::1]:4173"])
def test_explicit_loopback_development_origins_issue_insecure_cookie(origin: str) -> None:
    with browser_client(browser_origin=origin, cookie_secure=False) as api:
        response = api.post("/api/v1/auth/login", headers={**BEARER, "Origin": origin}, json={})
        assert response.status_code == 200
        assert "Secure" not in response.headers["set-cookie"]


def test_unconfigured_public_origin_uses_direct_https_origin_without_forwarded_trust() -> None:
    with browser_client(browser_origin=None) as api:
        response = api.post("/api/v1/auth/login", headers=LOGIN, json={})
        assert response.status_code == 200
    settings = Settings(state_backend="memory", api_token=TOKEN, _env_file=None)
    runtime = FakeRuntime()
    components = build_components(settings, reader=runtime, writer=runtime, model=ScriptedModel([]))
    with TestClient(create_app(settings, components), base_url="http://localhost:8000") as api:
        response = api.post(
            "/api/v1/auth/login",
            headers={**BEARER, "Origin": "http://localhost:8000", "X-Forwarded-Proto": "https"},
            json={},
        )
        assert response.status_code == 403


def test_session_endpoints_reject_extra_json_fields_without_echoing_secrets() -> None:
    with browser_client() as api:
        response = api.post("/api/v1/auth/login", headers=LOGIN, json={"token": "submitted-body-secret"})
        assert response.status_code == 422
        assert "submitted-body-secret" not in response.text
        assert "set-cookie" not in response.headers
