import json
from collections.abc import Sequence
from typing import Any, Literal, cast

from openai import APIStatusError, APITimeoutError, AsyncOpenAI, OpenAIError
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionMessageParam,
    ChatCompletionToolChoiceOptionParam,
    ChatCompletionToolUnionParam,
)
from openai.types.shared_params import ResponseFormatJSONSchema, ResponseFormatText

from docksight.adapters.outbound.models.common import parse_object, provider_error, strict_schema
from docksight.application.ports.models import ModelMessage, ModelReply, ToolCall, ToolSpec
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError, ErrorKind


def _messages(messages: Sequence[ModelMessage], require_tool_signatures: bool) -> list[dict[str, Any]]:
    """Replay provider messages intact, including opaque Gemini tool signatures."""
    rows: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "assistant" and message.native:
            rows.extend(message.native)
            continue
        rows.append(_message(message, require_tool_signatures))
    return rows


def _message(message: ModelMessage, require_tool_signatures: bool) -> dict[str, Any]:
    """Encode normalized history and mark server-created tool calls for Gemini replay."""
    row: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        calls: list[dict[str, Any]] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in message.tool_calls
        ]
        if require_tool_signatures:
            calls[0]["extra_content"] = {"google": {"thought_signature": "skip_thought_signature_validator"}}
        row["tool_calls"] = calls
    if message.role == "tool":
        row["tool_call_id"] = message.tool_call_id
    return row


def _reply(response: ChatCompletion, tool_output: bool) -> ModelReply:
    """Normalize native output or the forced final-diagnosis tool response."""
    item = response.choices[0]
    if item.finish_reason in {"length", "content_filter"}:
        raise DockSightError("model_incomplete", "Model response did not complete", ErrorKind.DEPENDENCY)
    if item.message.refusal:
        raise DockSightError("model_refusal", "Model declined this request", ErrorKind.VALIDATION)
    calls = tuple(
        ToolCall(call.id, call.function.name, parse_object(call.function.arguments))
        for call in item.message.tool_calls or []
        if call.type == "function"
    )
    content = item.message.content or ""
    if tool_output:
        if len(calls) != 1 or calls[0].name != "submit_diagnosis":
            raise DockSightError("invalid_model_response", "Model did not submit a diagnosis", ErrorKind.DEPENDENCY)
        content = json.dumps(calls[0].arguments)
        calls = ()
    return ModelReply(
        content,
        calls,
        native=(parse_object(item.message.model_dump(include={"role", "content", "tool_calls"}, exclude_none=True)),),
        input_tokens=response.usage.prompt_tokens if response.usage else None,
        output_tokens=response.usage.completion_tokens if response.usage else None,
    )


class CompatibleModel:
    """Support Chat Completions endpoints with native or tool-based JSON output."""

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        max_tokens: int = 4096,
        structured_output: Literal["native", "tool"] = "native",
        *,
        require_tool_signatures: bool = False,
    ) -> None:
        """Bind the compatible endpoint and its structured-output capability."""
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.structured_output = structured_output
        self.require_tool_signatures = require_tool_signatures

    def _output_options(
        self, tools: Sequence[ToolSpec], schema: JsonObject | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | str, dict[str, Any]]:
        """Select tool calling, native JSON schema, or a forced submission tool."""
        functions: list[dict[str, Any]] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": strict_schema(tool.parameters),
                    "strict": True,
                },
            }
            for tool in tools
        ]
        response_format: dict[str, Any] = {"type": "text"}
        choice: dict[str, Any] | str = "auto" if functions else "none"
        if schema is not None and self.structured_output == "tool":
            functions = [
                {
                    "type": "function",
                    "function": {
                        "name": "submit_diagnosis",
                        "description": "Return the final validated diagnosis",
                        "parameters": strict_schema(schema),
                    },
                }
            ]
            choice = {"type": "function", "function": {"name": "submit_diagnosis"}}
        elif schema is not None:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "docksight_response",
                    "schema": strict_schema(schema),
                    "strict": True,
                },
            }
        return functions, choice, response_format

    async def complete(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec] = (),
        schema: JsonObject | None = None,
    ) -> ModelReply:
        """Request a bounded Chat Completions reply and sanitize provider failures."""
        functions, choice, response_format = self._output_options(tools, schema)
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=cast(list[ChatCompletionMessageParam], _messages(messages, self.require_tool_signatures)),
                tools=cast(list[ChatCompletionToolUnionParam], functions),
                tool_choice=cast(ChatCompletionToolChoiceOptionParam, choice),
                response_format=cast(ResponseFormatJSONSchema | ResponseFormatText, response_format),
                max_tokens=self.max_tokens,
                temperature=0,
                stream=False,
            )
            return _reply(response, schema is not None and self.structured_output == "tool")
        except APIStatusError as exc:
            raise provider_error(exc.status_code) from exc
        except APITimeoutError as exc:
            raise DockSightError("provider_timeout", "Model provider timed out", ErrorKind.TIMEOUT) from exc
        except OpenAIError as exc:
            raise DockSightError(
                "provider_unavailable", "Model provider is unavailable", ErrorKind.UNAVAILABLE
            ) from exc
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise DockSightError(
                "invalid_model_response", "Model provider returned an invalid response", ErrorKind.DEPENDENCY
            ) from exc
