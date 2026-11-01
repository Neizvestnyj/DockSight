import json
from importlib.metadata import version

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from docksight.adapters.outbound.models.anthropic import AnthropicModel
from docksight.adapters.outbound.models.compatible import CompatibleModel
from docksight.adapters.outbound.models.openai import OpenAIModel
from docksight.adapters.outbound.models.status import ModelAvailability
from docksight.application.ports.models import ModelMessage
from docksight.bootstrap import Settings, build_components
from docksight.main import create_app
from tests.fakes import FakeRuntime


def test_standard_provider_keys_load_from_dotenv(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dotenv credentials configure secondary providers without relying on process environment mutation."""
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "DOCKSIGHT_OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAI_API_KEY=openai-dotenv\nANTHROPIC_API_KEY=anthropic-dotenv\nGEMINI_API_KEY=gemini-dotenv\n"
    )
    settings = Settings(api_token="test-token-at-least-24-chars", _env_file=env_file)
    assert settings.openai_api_key.get_secret_value() == "openai-dotenv"
    assert settings.anthropic_api_key.get_secret_value() == "anthropic-dotenv"
    assert settings.gemini_api_key.get_secret_value() == "gemini-dotenv"


@pytest.mark.parametrize("models", [{"unknown": ["x"]}, {"openai": [""]}, {"openai": ["x"] * 101}])
def test_fallback_configuration_rejects_unknown_or_unbounded_ids(models: dict[str, list[str]]) -> None:
    with pytest.raises(ValidationError):
        Settings(api_token="test-token-at-least-24-chars", provider_fallback_models=models, _env_file=None)


@pytest.mark.parametrize("explicit_key", [None, "explicit-gemini-key"])
@pytest.mark.parametrize("base_url", [None, "https://gateway.example.test/gemini/"])
async def test_gemini_wiring_uses_google_credentials_and_endpoint(
    monkeypatch: pytest.MonkeyPatch, explicit_key: str | None, base_url: str | None
) -> None:
    """Keep Gemini generation and metadata on the same origin without OpenAI environment defaults."""
    monkeypatch.setenv("GEMINI_API_KEY", "environment-gemini-key")
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unrelated.example.test/")
    settings = Settings(
        api_token="test-token-at-least-24-chars",
        provider="gemini",
        model="gemini-2.5-flash-lite",
        model_api_key=explicit_key,
        model_base_url=base_url,
        _env_file=None,
    )
    runtime = FakeRuntime()
    components = build_components(settings, reader=runtime, writer=runtime)
    try:
        generation, probe = components.diagnostics.model, components.status.probe
        assert isinstance(generation, CompatibleModel)
        assert isinstance(probe, ModelAvailability)
        assert str(generation.client.base_url) == (
            base_url or "https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        assert str(probe.client.base_url) == str(generation.client.base_url)
        assert probe.provider == "gemini"
        assert probe.client.headers["Authorization"] == f"Bearer {explicit_key or 'environment-gemini-key'}"
        assert generation.model == "gemini-2.5-flash-lite"
        assert generation.require_tool_signatures
        assert generation.client.max_retries == 0
    finally:
        await components.close()


def test_gemini_requires_its_own_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DOCKSIGHT_MODEL_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-openai-key")
    settings = Settings(api_token="test-token-at-least-24-chars", provider="gemini", _env_file=None)
    runtime = FakeRuntime()
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        build_components(settings, reader=runtime, writer=runtime)


@pytest.mark.parametrize(
    "compatible_key,expected",
    [(None, "local-no-key"), ("compatible-gateway-key", "compatible-gateway-key")],
)
async def test_compatible_endpoint_never_receives_openai_credentials(
    monkeypatch: pytest.MonkeyPatch, compatible_key: str | None, expected: str
) -> None:
    """Keep OpenAI keys away from a third-party endpoint configured as the compatible provider."""
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-openai-key")
    monkeypatch.setenv("DOCKSIGHT_OPENAI_API_KEY", "unrelated-docksight-openai-key")
    monkeypatch.delenv("DOCKSIGHT_MODEL_API_KEY", raising=False)
    settings = Settings(
        api_token="test-token-at-least-24-chars",
        provider="compatible",
        model="local-model",
        model_base_url="http://127.0.0.1:8080/v1/",
        compatible_api_key=compatible_key,
        _env_file=None,
    )
    runtime = FakeRuntime()
    components = build_components(settings, reader=runtime, writer=runtime)
    try:
        generation, probe = components.diagnostics.model, components.status.probe
        assert isinstance(generation, CompatibleModel)
        assert isinstance(probe, ModelAvailability)
        assert generation.client.api_key == expected
        assert probe.client.headers["Authorization"] == f"Bearer {expected}"
    finally:
        await components.close()


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


def test_named_tokens_replace_the_single_token_and_map_to_their_actors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKSIGHT_API_TOKEN", raising=False)
    monkeypatch.setenv(
        "DOCKSIGHT_API_TOKENS",
        json.dumps({"alice": "alice-token-at-least-24-characters", "ci.bot": "bot-token-at-least-24-characters"}),
    )
    settings = Settings(_env_file=None)
    assert settings.api_credentials() == {
        "alice": "alice-token-at-least-24-characters",
        "ci.bot": "bot-token-at-least-24-characters",
    }


@pytest.mark.parametrize(
    "api_tokens",
    [
        {"alice": "short"},
        {"bad name": "alice-token-at-least-24-characters"},
        {"alice": "shared-token-at-least-24-characters", "bob": "shared-token-at-least-24-characters"},
        {"operator": "other-token-at-least-24-characters"},
    ],
)
def test_named_tokens_reject_weak_shared_or_unsafe_identities(api_tokens: dict[str, str]) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(api_token="test-token-at-least-24-chars", api_tokens=api_tokens, _env_file=None)
    assert not any(token in str(error.value) for token in api_tokens.values())


def test_health_does_not_require_a_docker_connection() -> None:
    settings = Settings(api_token="test-token-at-least-24-chars", _env_file=None)
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "version": version("docksight")}
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
