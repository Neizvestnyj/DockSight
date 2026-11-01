import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from docksight.adapters.inbound.http.errors import install_errors
from docksight.domain.errors import DockSightError, ErrorKind


@pytest.mark.parametrize(
    ("code", "kind", "status"),
    [
        ("custom_failure", ErrorKind.INVALID, 400),
        ("forbidden", ErrorKind.FORBIDDEN, 403),
        ("group_not_found", ErrorKind.NOT_FOUND, 404),
        ("group_not_found", ErrorKind.CONFLICT, 409),
        ("invalid_query", ErrorKind.VALIDATION, 422),
        ("provider_rate_limit", ErrorKind.RATE_LIMIT, 429),
        ("invalid_hosts", ErrorKind.CONFIGURATION, 500),
        ("invalid_response", ErrorKind.DEPENDENCY, 502),
        ("provider_unavailable", ErrorKind.UNAVAILABLE, 503),
        ("provider_timeout", ErrorKind.TIMEOUT, 504),
        ("provider_not_configured", ErrorKind.VALIDATION, 422),
        ("provider_not_configured", ErrorKind.UNAVAILABLE, 503),
        ("resource_outside_group", ErrorKind.VALIDATION, 422),
        ("resource_outside_group", ErrorKind.DEPENDENCY, 502),
    ],
)
def test_application_failures_keep_http_status_and_public_envelope(code: str, kind: ErrorKind, status: int) -> None:
    app = FastAPI()
    install_errors(app)

    @app.get("/failure")
    async def failure() -> None:
        """Expose one semantic failure through the actual registered HTTP boundary."""
        raise DockSightError(code, "Safe failure details", kind)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/failure")
    assert response.status_code == status
    assert response.json() == {"code": code, "message": "Safe failure details"}
    assert "x-request-id" not in response.headers


def test_unspecified_failure_category_preserves_the_default_client_error() -> None:
    app = FastAPI()
    install_errors(app)

    @app.get("/failure")
    async def failure() -> None:
        """Exercise the error constructor's existing default at the HTTP boundary."""
        raise DockSightError("custom_failure", "Safe failure details")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/failure")
    assert response.status_code == 400
    assert response.json() == {"code": "custom_failure", "message": "Safe failure details"}


def test_application_failure_keeps_the_request_identifier_in_body_and_headers() -> None:
    app = FastAPI()
    install_errors(app)

    @app.get("/failure")
    async def failure(request: Request) -> None:
        """Fail after binding a safe request identifier as the outer middleware does."""
        request.state.request_id = "request-123"
        raise DockSightError("action_conflict", "Action uses another idempotency key", ErrorKind.CONFLICT)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/failure")
    assert response.status_code == 409
    assert response.headers["x-request-id"] == "request-123"
    assert response.json() == {
        "code": "action_conflict",
        "message": "Action uses another idempotency key",
        "request_id": "request-123",
    }
