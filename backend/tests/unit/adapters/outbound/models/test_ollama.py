import json

import httpx
import pytest

from docksight.adapters.outbound.models.ollama import OllamaModel
from docksight.application.ports.models import ModelMessage, ToolSpec
from docksight.domain.errors import DockSightError


async def test_ollama_parses_tools_and_sends_native_schema() -> None:
    requests: list[dict] = []

    def reply(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "inspect_container",
                                "arguments": {"container_id": "abc"},
                            }
                        },
                    ],
                },
                "done": True,
                "prompt_eval_count": 8,
                "eval_count": 3,
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(reply), base_url="http://ollama"
    ) as client:
        model = OllamaModel(client, "test-model")
        tool = ToolSpec("inspect_container", "Inspect", {"type": "object", "properties": {}})
        result = await model.complete([ModelMessage("user", "Inspect worker")], [tool])
        assert result.tool_calls[0].arguments == {"container_id": "abc"}
        assert result.input_tokens == 8
        assert requests[0]["stream"] is False
        assert requests[0]["think"] is False
        await model.complete([ModelMessage("user", "Respond")], schema={"type": "object"})
        assert requests[1]["format"] == {"type": "object"}


@pytest.mark.parametrize("status", [400, 429, 500])
async def test_provider_errors_do_not_expose_response_bodies(status: int) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status, text="api_key=private-sentinel")
        ),
        base_url="http://ollama",
    ) as client:
        with pytest.raises(DockSightError) as error:
            await OllamaModel(client, "test").complete([ModelMessage("user", "Hello")])
        assert "private-sentinel" not in str(error.value)
        assert error.value.status == (429 if status == 429 else 422 if status == 400 else 503)
