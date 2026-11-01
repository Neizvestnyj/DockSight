import json

import httpx2
import pytest
from openai import AsyncOpenAI

from docksight.adapters.outbound.models.compatible import CompatibleModel
from docksight.application.ports.models import ModelMessage, ToolCall, ToolSpec
from docksight.domain.errors import DockSightError, ErrorKind


async def test_gemini_retired_model_error_is_safe_and_distinct_from_unsupported_requests() -> None:
    """Handle Google's observed array-shaped 404 without returning its model advice or private details."""
    upstream = [
        {
            "error": {
                "code": 404,
                "message": (
                    "This model models/gemini-2.5-flash-lite is no longer available to new users. "
                    "Please update your code to use models/gemini-3.5-flash-lite "
                    "for the latest features and improvements. "
                    "We recommend you to use the Interactions API (https://ai.google.dev/gemini-api/docs/get-started)."
                ),
                "status": "NOT_FOUND",
                "details": [{"api_key": "private-provider-key", "request": "private-prompt"}],
            }
        }
    ]
    async with AsyncOpenAI(
        api_key="private-provider-key",
        max_retries=0,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(lambda _: httpx2.Response(404, json=upstream))),
    ) as client:
        with pytest.raises(DockSightError) as caught:
            await CompatibleModel(client, "gemini-2.5-flash-lite", require_tool_signatures=True).complete(
                [ModelMessage("user", "private-prompt")]
            )
    error = caught.value
    assert error.code == "model_unavailable"
    assert error.kind == ErrorKind.VALIDATION
    assert "Check the model name and your access" in error.message
    assert all(
        value not in str(error) for value in ("private-provider-key", "private-prompt", "gemini-3.5", "Interactions")
    )


async def test_gemini_tool_signature_survives_tool_result_and_structured_output() -> None:
    """Replay opaque signatures in place so a second Gemini request can consume tool evidence."""
    payloads: list[dict] = []
    signed_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "list_containers", "arguments": "{}"},
        "extra_content": {"google": {"thought_signature": "opaque-signature"}},
    }

    def reply(request: httpx2.Request) -> httpx2.Response:
        """Return a signed tool call followed by a JSON diagnosis."""
        payloads.append(json.loads(request.content))
        message = (
            {"role": "assistant", "content": None, "tool_calls": [signed_call]}
            if len(payloads) == 1
            else {"role": "assistant", "content": '{"summary":"OK"}'}
        )
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl_1",
                "object": "chat.completion",
                "created": 1,
                "model": "gemini-2.5-flash-lite",
                "choices": [
                    {"index": 0, "finish_reason": "tool_calls" if len(payloads) == 1 else "stop", "message": message}
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
            },
        )

    async with AsyncOpenAI(
        api_key="test",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(reply)),
    ) as client:
        model = CompatibleModel(client, "gemini-2.5-flash-lite", require_tool_signatures=True)
        messages = [ModelMessage("user", "Inspect containers")]
        first = await model.complete(messages, [ToolSpec("list_containers", "List containers", {"type": "object"})])
        assert first.tool_calls[0].name == "list_containers"
        messages.extend(
            [
                ModelMessage("assistant", first.content, first.tool_calls, native=first.native),
                ModelMessage("tool", '{"containers":[]}', tool_call_id="call_1", tool_name="list_containers"),
            ]
        )
        final = await model.complete(messages, schema={"type": "object", "properties": {"summary": {"type": "string"}}})
    assert payloads[1]["messages"][1]["tool_calls"] == [signed_call]
    assert payloads[1]["messages"][2]["tool_call_id"] == "call_1"
    assert payloads[1]["response_format"]["type"] == "json_schema"
    assert final.content == '{"summary":"OK"}'
    assert (final.input_tokens, final.output_tokens) == (12, 4)


async def test_gemini_marks_server_precollected_tools_without_model_signatures() -> None:
    """Allow the application's deterministic Docker reads in the current Gemini turn."""
    payloads: list[dict] = []

    def reply(request: httpx2.Request) -> httpx2.Response:
        """Capture a request with server-created evidence and return a completed answer."""
        payloads.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl_1",
                "object": "chat.completion",
                "created": 1,
                "model": "gemini-3.5-flash-lite",
                "choices": [
                    {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "Ready"}}
                ],
            },
        )

    async with AsyncOpenAI(
        api_key="test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(reply)),
    ) as client:
        await CompatibleModel(client, "gemini-3.5-flash-lite", require_tool_signatures=True).complete(
            [
                ModelMessage("user", "Inspect containers"),
                ModelMessage("assistant", tool_calls=(ToolCall("seed_1", "list_containers", {}),)),
                ModelMessage("tool", '{"containers":[]}', tool_call_id="seed_1", tool_name="list_containers"),
            ]
        )
    call = payloads[0]["messages"][1]["tool_calls"][0]
    assert call["extra_content"]["google"]["thought_signature"] == "skip_thought_signature_validator"


async def test_compatible_endpoint_can_return_schema_through_a_forced_tool() -> None:
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
