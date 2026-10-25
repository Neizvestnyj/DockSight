import json

import httpx2
import pytest
from anthropic import AsyncAnthropic

from docksight.adapters.outbound.models.anthropic import AnthropicModel
from docksight.application.ports.models import ModelMessage, ToolSpec
from docksight.domain.errors import DockSightError


async def test_anthropic_tool_results_use_native_message_blocks() -> None:
    requests: list[dict] = []

    def reply(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "inspect_container",
                        "input": {"container_id": "abc"},
                    }
                ],
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 4},
            },
        )

    async with AsyncAnthropic(
        api_key="test",
        max_retries=0,
        http_client=httpx2.AsyncClient(
            transport=httpx2.MockTransport(reply),
        ),
    ) as client:
        model = AnthropicModel(client, "claude-test")
        tool = ToolSpec("inspect_container", "Inspect", {"type": "object", "properties": {}})
        result = await model.complete(
            [ModelMessage("system", "Read only"), ModelMessage("user", "Inspect")], [tool]
        )
        assert result.tool_calls[0].id == "tool_1"
        await model.complete(
            [
                ModelMessage("assistant", result.content, result.tool_calls, native=result.native),
                ModelMessage("tool", "{}", tool_call_id="tool_1", tool_name="inspect_container"),
            ],
            [tool],
        )
    assert requests[0]["system"] == "Read only"
    assert requests[1]["messages"][-1]["content"][0]["tool_use_id"] == "tool_1"


async def test_rate_limit_is_reported_without_automatic_retries() -> None:
    requests: list[str] = []

    def reply(request: httpx2.Request) -> httpx2.Response:
        requests.append(str(request.url))
        return httpx2.Response(
            429,
            json={
                "type": "error",
                "error": {"type": "rate_limit_error", "message": "private-sentinel"},
            },
        )

    async with AsyncAnthropic(
        api_key="test",
        max_retries=0,
        http_client=httpx2.AsyncClient(
            transport=httpx2.MockTransport(reply),
        ),
    ) as client:
        with pytest.raises(DockSightError) as error:
            await AnthropicModel(client, "claude-test").complete([ModelMessage("user", "Test")])
    assert len(requests) == 1
    assert error.value.status == 429
    assert "private-sentinel" not in str(error.value)
