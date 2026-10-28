import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from docksight.adapters.outbound.models.anthropic import AnthropicModel
from docksight.adapters.outbound.models.openai import OpenAIModel
from docksight.adapters.outbound.models.status import ModelAvailability
from docksight.application.ports.models import ModelMessage
from docksight.bootstrap import Settings, build_components
from docksight.main import create_app
from tests.fakes import FakeRuntime


@pytest.mark.parametrize("provider,variable", [("openai", "OPENAI_BASE_URL"), ("anthropic", "ANTHROPIC_BASE_URL")])
async def test_status_probe_uses_the_generation_clients_effective_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    variable: str,
) -> None:
    """Keep gateway credentials on the same configured origin for generation and metadata."""
    monkeypatch.setenv(variable, "https://gateway.example.test/custom/")
    monkeypatch.setenv("OPENAI_ORG_ID", "test-organization")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "test-project")
    settings = Settings(
        api_token="test-token-at-least-24-chars", provider=provider, model_api_key="gateway-test-key", _env_file=None
    )
    runtime = FakeRuntime()
    components = build_components(settings, reader=runtime, writer=runtime)
    try:
        probe = components.status.probe
        assert isinstance(probe, ModelAvailability)
        generation = components.diagnostics.model
        assert isinstance(generation, (OpenAIModel, AnthropicModel))
        assert str(probe.client.base_url) == str(generation.client.base_url)
        assert str(probe.client.base_url) == "https://gateway.example.test/custom/"
        assert probe.client.headers["Authorization"] == "Bearer gateway-test-key"
        if provider == "openai":
            assert probe.client.headers["OpenAI-Organization"] == "test-organization"
            assert probe.client.headers["OpenAI-Project"] == "test-project"
        else:
            assert probe.client.headers["anthropic-version"] == generation.client.default_headers["anthropic-version"]
    finally:
        await components.close()


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


async def test_configured_ollama_context_reaches_native_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preserve the operator's context override when wiring the native Ollama client."""
    payloads: list[dict] = []

    def reply(request: httpx.Request) -> httpx.Response:
        """Capture the real adapter's request and return a native chat response."""
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "Ready"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 8,
                "eval_count": 1,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(reply), base_url="http://ollama")

    def create_client(**options: object) -> httpx.AsyncClient:
        """Use an in-process transport while keeping production settings and adapter wiring."""
        return client

    monkeypatch.setattr("docksight.bootstrap.httpx.AsyncClient", create_client)
    settings = Settings(
        api_token="test-token-at-least-24-chars", provider="ollama", ollama_context_length=8192, _env_file=None
    )
    runtime = FakeRuntime()
    components = build_components(settings, reader=runtime, writer=runtime)
    try:
        await components.diagnostics.model.complete([ModelMessage("user", "Inspect worker")])
        assert payloads[0]["options"]["num_ctx"] == 8192
    finally:
        await components.close()
