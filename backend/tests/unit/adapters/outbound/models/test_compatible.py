import json

import httpx2
from openai import AsyncOpenAI

from docksight.adapters.outbound.models.compatible import CompatibleModel
from docksight.application.ports.models import ModelMessage


async def test_compatible_endpoint_can_return_schema_through_a_forced_tool() -> None:
    """Verify compatible endpoint can return schema through a forced tool."""
    requests: list[dict] = []

    def reply(request: httpx2.Request) -> httpx2.Response:
        """Validate the outgoing provider payload and return the next fixture response."""
        requests.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl_1",
                "object": "chat.completion",
                "created": 1,
                "model": "custom",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "submit_diagnosis",
                                        "arguments": '{"summary":"OK"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            },
        )

    async with AsyncOpenAI(
        api_key="test",
        base_url="http://custom/v1",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(reply)),
    ) as client:
        result = await CompatibleModel(client, "custom", structured_output="tool").complete(
            [ModelMessage("user", "Respond")],
            schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        )
    assert json.loads(result.content) == {"summary": "OK"}
    assert not result.tool_calls
    assert requests[0]["tool_choice"]["function"]["name"] == "submit_diagnosis"
