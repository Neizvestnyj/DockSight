import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from docksight.bootstrap import Settings
from docksight.main import create_app


def test_missing_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKSIGHT_API_TOKEN", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_invalid_provider_and_short_token_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(api_token="short", provider="unknown", _env_file=None)


def test_health_does_not_require_a_docker_connection() -> None:
    settings = Settings(api_token="test-token-at-least-24-chars", _env_file=None)
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "version": "0.1.0"}
        assert response.headers["x-request-id"]


def test_api_does_not_expose_configured_hosts_without_authentication() -> None:
    settings = Settings(api_token="test-token-at-least-24-chars", _env_file=None)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/hosts")
        assert response.status_code == 401
        assert "test-token" not in response.text
