import json

import httpx
import pytest

from docksight.adapters.outbound.models.ollama import OllamaModel
from docksight.application.ports.models import ModelMessage, ToolSpec
from docksight.domain.errors import DockSightError


async def test_structured_output_schema_descriptions_reach_the_model_without_mutating_history() -> None:
    payloads: list[dict] = []

    def reply(request: httpx.Request) -> httpx.Response:
        """Capture the actual provider request while returning a bounded structured answer."""
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": '{"immediate":"Database connection failed"}'}})

    schema = {
        "type": "object",
        "properties": {"immediate": {"type": "string", "description": "Explain the failure in natural language"}},
        "required": ["immediate"],
    }
    messages = [ModelMessage("system", "Keep observed data separate"), ModelMessage("user", "Inspect worker")]
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply), base_url="http://ollama") as client:
        await OllamaModel(client, "test-model").complete(messages, schema=schema)
    assert payloads[0]["format"] == schema
    content = "\n".join(row["content"] for row in payloads[0]["messages"])
    assert "Explain the failure in natural language" in content
    assert '"immediate"' in content
    assert payloads[0]["messages"][:2] == [
        {"role": "system", "content": "Keep observed data separate"},
        {"role": "user", "content": "Inspect worker"},
    ]
    assert messages == [ModelMessage("system", "Keep observed data separate"), ModelMessage("user", "Inspect worker")]


async def test_ollama_parses_tools_and_sends_native_schema() -> None:
    requests: list[dict] = []

    def reply(request: httpx.Request) -> httpx.Response:
        """Validate the outgoing provider payload and return the next fixture response."""
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

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply), base_url="http://ollama") as client:
        model = OllamaModel(client, "test-model")
        tool = ToolSpec("inspect_container", "Inspect", {"type": "object", "properties": {}})
        result = await model.complete([ModelMessage("user", "Inspect worker")], [tool])
        assert result.tool_calls[0].arguments == {"container_id": "abc"}
        assert result.input_tokens == 8
        assert requests[0]["stream"] is False
        assert requests[0]["think"] is False
        assert requests[0]["options"].get("num_ctx") == 16384
        await model.complete([ModelMessage("user", "Respond")], schema={"type": "object"})
        assert requests[1]["format"] == {"type": "object"}
        assert requests[1]["options"].get("num_ctx") == 16384


@pytest.mark.parametrize("status", [400, 429, 500])
async def test_provider_errors_do_not_expose_response_bodies(status: int) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text="api_key=private-sentinel")),
        base_url="http://ollama",
    ) as client:
        with pytest.raises(DockSightError) as error:
            await OllamaModel(client, "test").complete([ModelMessage("user", "Hello")])
        assert "private-sentinel" not in str(error.value)
        assert error.value.status == (429 if status == 429 else 422 if status == 400 else 503)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        3,
        {"message": []},
        {"message": None},
        {"message": {"content": []}},
        {"message": {"tool_calls": {"function": {}}}},
        {"message": {"tool_calls": [[]]}},
        {"message": {"tool_calls": [{"function": []}]}},
        {"message": {"tool_calls": [{"function": {"name": [], "arguments": {}}}]}},
        {"message": {}, "eval_count": []},
    ],
)
async def test_malformed_json_shapes_raise_typed_provider_error(payload: object) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)), base_url="http://ollama"
    ) as client:
        with pytest.raises(DockSightError) as error:
            await OllamaModel(client, "test").complete([ModelMessage("user", "Hello")])
        assert error.value.code == "invalid_model_response"
