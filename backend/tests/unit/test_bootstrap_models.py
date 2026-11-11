import asyncio
import json

import httpx2
import pytest
from openai import AsyncOpenAI

from docksight.adapters.outbound.models.openai import OpenAIModel
from docksight.adapters.outbound.models.status import ModelAvailability
from docksight.application.model_catalog import ModelSelection
from docksight.application.ports.models import ModelMessage
from docksight.bootstrap import Settings, build_components
from tests.fakes import FakeRuntime, ScriptedModel


async def test_secondary_selections_share_clients_and_redact_all_configured_keys() -> None:
    """Model copies share one provider connection and all selected diagnoses share credential redaction."""
    settings = Settings(
        state_backend="memory",
        api_token="test-token-at-least-24-characters",
        model_api_key="legacy-secret",
        openai_api_key="secondary-secret",
        anthropic_api_key="other-provider-secret",
        provider_fallback_models={"openai": ("first", "second")},
        _env_file=None,
    )
    runtime = FakeRuntime()
    components = build_components(settings, reader=runtime, writer=runtime, model=ScriptedModel([]))
    try:
        choices = components.models
        assert choices is not None
        assert components.closers == []
        selections = await asyncio.gather(
            choices.select(ModelSelection(provider="openai", model="first")),
            choices.select(ModelSelection(provider="openai", model="second")),
        )
        first, first_probe = selections[0]
        second, second_probe = selections[1]
        assert isinstance(first, OpenAIModel) and isinstance(second, OpenAIModel)
        assert first is not second and first.client is second.client
        assert first.model == "first" and second.model == "second"
        assert isinstance(first_probe, ModelAvailability) and isinstance(second_probe, ModelAvailability)
        assert first_probe.client is second_probe.client
        assert first_probe.model == "first" and second_probe.model == "second"
        assert first_probe.client.headers["Authorization"] == "Bearer secondary-secret"
        assert len(components.closers) == 2
        assert choices.catalogs["openai"].task is None
        text = components.diagnostics.redactor.text("legacy-secret secondary-secret other-provider-secret")
        assert "secret" not in text
        assert components.status.model == settings.model
    finally:
        await components.close()


@pytest.mark.parametrize("provider", ["compatible", "gemini"])
async def test_secondary_provider_uses_its_configured_tool_output_mode(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A secondary connection can submit schema output through a tool independently of the default provider."""
    payloads: list[dict] = []

    def reply(request: httpx2.Request) -> httpx2.Response:
        """Capture the selected adapter's actual request and supply a forced tool result."""
        payloads.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "fixture",
                "object": "chat.completion",
                "created": 1,
                "model": "fixture-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "result",
                                    "type": "function",
                                    "function": {"name": "submit_diagnosis", "arguments": '{"summary":"OK"}'},
                                }
                            ],
                        },
                    }
                ],
            },
        )

    def create_client(**options: object) -> AsyncOpenAI:
        """Replace network I/O while retaining production provider/client wiring."""
        return AsyncOpenAI(**options, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(reply)))

    monkeypatch.setattr("docksight.bootstrap.AsyncOpenAI", create_client)
    settings = Settings(
        state_backend="memory",
        api_token="test-token-at-least-24-characters",
        compatible_base_url="http://compatible.example.test/v1/",
        gemini_api_key="fixture-gemini-key",
        compatible_structured_output="tool",
        gemini_structured_output="tool",
        provider_fallback_models={provider: ("fixture-model",)},
        _env_file=None,
    )
    runtime = FakeRuntime()
    components = build_components(settings, reader=runtime, writer=runtime, model=ScriptedModel([]))
    try:
        assert components.models is not None
        selected, _ = await components.models.select(ModelSelection(provider=provider, model="fixture-model"))
        result = await selected.complete(
            [ModelMessage("user", "Explain")],
            schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        )
        assert payloads[0]["response_format"]["type"] == "text"
        assert payloads[0]["tool_choice"]["function"]["name"] == "submit_diagnosis"
        assert json.loads(result.content) == {"summary": "OK"}
        assert components.diagnostics.model_identity == ("ollama", "qwen3.5:9b")
    finally:
        await components.close()
