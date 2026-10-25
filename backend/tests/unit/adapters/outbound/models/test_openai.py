import json

import httpx2
from openai import AsyncOpenAI
from openai.types.responses import ResponseFunctionToolCallParam
from pydantic import TypeAdapter

from docksight.adapters.outbound.models.openai import OpenAIModel
from docksight.application.ports.models import ModelMessage, ToolSpec


async def test_responses_preserves_native_reasoning_and_call_ids() -> None:
    requests: list[dict] = []
    output = [
        {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque-state"},
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "inspect_container",
            "arguments": '{"container_id":"abc"}',
            "status": "completed",
            "async": False,
            "namespace": None,
        },
    ]

    def reply(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "resp_1",
                "object": "response",
                "created_at": 1,
                "model": "gpt-test",
                "status": "completed",
                "output": output,
                "usage": {"input_tokens": 9, "output_tokens": 3, "total_tokens": 12},
            },
        )

    async with AsyncOpenAI(
        api_key="test",
        max_retries=0,
        http_client=httpx2.AsyncClient(
            transport=httpx2.MockTransport(reply),
        ),
    ) as client:
        model = OpenAIModel(client, "gpt-test")
        tool = ToolSpec(
            "inspect_container",
            "Inspect",
            {
                "type": "object",
                "properties": {"container_id": {"type": "string"}},
                "required": ["container_id"],
                "additionalProperties": False,
            },
        )
        result = await model.complete([ModelMessage("user", "Inspect")], [tool])
        assert result.tool_calls[0].id == "call_1"
        assert result.tool_calls[0].arguments == {"container_id": "abc"}
        await model.complete(
            [
                ModelMessage("user", "Inspect"),
                ModelMessage("assistant", result.content, result.tool_calls, native=result.native),
                ModelMessage("tool", "{}", tool_call_id="call_1", tool_name="inspect_container"),
            ],
            [tool],
        )
    assert requests[0]["store"] is False
    assert requests[1]["input"][1]["encrypted_content"] == "opaque-state"
    assert requests[1]["input"][-1]["call_id"] == "call_1"
    replayed = next(item for item in requests[1]["input"] if item.get("type") == "function_call")
    TypeAdapter(ResponseFunctionToolCallParam).validate_python(replayed)
    assert "async_" not in replayed
    assert replayed["async"] is False
