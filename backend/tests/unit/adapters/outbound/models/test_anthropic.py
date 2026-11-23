import json

import httpx2
import pytest
from anthropic import AsyncAnthropic
from anthropic.types import ToolUseBlockParam
from pydantic import TypeAdapter

from docksight.adapters.outbound.models.anthropic import AnthropicModel
from docksight.application.ports.models import ModelMessage, ToolSpec
from docksight.domain.errors import DockSightError, ErrorKind


async def test_anthropic_tool_results_use_native_message_blocks() -> None:
    requests: list[dict] = []

    def reply(request: httpx2.Request) -> httpx2.Response:
        """Validate the outgoing provider payload and return the next fixture response."""
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
                        "input": {"container_id": "abc", "optional": None},
                        "caller": None,
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
        tool = ToolSpec(
            "inspect_container",
            "Inspect",
            {
                "type": "object",
                "properties": {
                    "container_id": {"type": "string"},
                    "optional": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
                "required": ["container_id", "optional"],
                "additionalProperties": False,
            },
        )
        result = await model.complete([ModelMessage("system", "Read only"), ModelMessage("user", "Inspect")], [tool])
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
    replayed = requests[1]["messages"][0]["content"][0]
    TypeAdapter(ToolUseBlockParam).validate_python(replayed)
    assert replayed["input"]["optional"] is None


@pytest.mark.parametrize(
    ("failure", "kind", "code"),
    [
        (None, ErrorKind.RATE_LIMIT, "provider_rate_limit"),
        (httpx2.ReadTimeout, ErrorKind.TIMEOUT, "provider_timeout"),
        (httpx2.ConnectError, ErrorKind.UNAVAILABLE, "provider_unavailable"),
    ],
)
async def test_provider_failures_are_reported_without_automatic_retries(
    failure: type[httpx2.RequestError] | None, kind: ErrorKind, code: str
) -> None:
    requests: list[str] = []

    def reply(request: httpx2.Request) -> httpx2.Response:
        """Validate the outgoing provider payload and return the next fixture response."""
        requests.append(str(request.url))
        if failure is not None:
            raise failure("private-sentinel", request=request)
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
    assert (error.value.kind, error.value.code) == (kind, code)
    assert "private-sentinel" not in str(error.value)


@pytest.mark.parametrize(("reason", "code"), [("refusal", "model_refusal"), ("max_tokens", "model_truncated")])
async def test_incomplete_structured_messages_are_diagnosis_failures(reason: str, code: str) -> None:
    def reply(request: httpx2.Request) -> httpx2.Response:
        """Return a stopped response that contains text despite its unsuccessful stop reason."""
        output_format = json.loads(request.content)["output_config"]["format"]
        assert output_format["type"] == "json_schema"
        assert output_format["schema"]["required"] == ["summary"]
        return httpx2.Response(
            200,
            json={"stop_reason": reason, "content": [{"type": "text", "text": "private-sentinel"}]},
        )

    async with AsyncAnthropic(
        api_key="test", max_retries=0, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(reply))
    ) as client:
        with pytest.raises(DockSightError) as caught:
            await AnthropicModel(client, "claude-test").complete(
                [ModelMessage("user", "Diagnose")],
                schema={"type": "object", "properties": {"summary": {"type": "string"}}},
            )
    assert caught.value.code == code
    assert "private-sentinel" not in caught.value.message
