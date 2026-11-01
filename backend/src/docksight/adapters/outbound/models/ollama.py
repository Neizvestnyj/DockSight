import json
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from docksight.adapters.outbound.models.common import parse_object, provider_error
from docksight.application.ports.models import ModelMessage, ModelReply, ToolCall, ToolSpec
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError, ErrorKind


class _Function(BaseModel):
    """Validate the native tool function before reading its fields."""

    model_config = ConfigDict(strict=True)
    name: str = Field(min_length=1, max_length=128)
    arguments: JsonObject | str


class _Call(BaseModel):
    """Validate one provider tool call and optional identifier."""

    model_config = ConfigDict(strict=True)
    id: str | None = Field(default=None, max_length=256)
    function: _Function


class _Message(BaseModel):
    """Validate assistant text and the native tool-call collection."""

    model_config = ConfigDict(strict=True)
    content: str = Field(default="", max_length=1048576)
    tool_calls: list[_Call] = Field(default_factory=list[_Call], max_length=64)


class _Response(BaseModel):
    """Validate external reply shapes and usage counters before parsing."""

    model_config = ConfigDict(strict=True)
    message: _Message
    done_reason: str | None = None
    prompt_eval_count: int | None = Field(default=None, ge=0)
    eval_count: int | None = Field(default=None, ge=0)


def _messages(messages: Sequence[ModelMessage]) -> list[dict[str, Any]]:
    """Encode native Ollama tool calls and tool-name associations."""
    rows: list[dict[str, Any]] = []
    for message in messages:
        row: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.tool_calls:
            row["tool_calls"] = [
                {"function": {"name": call.name, "arguments": call.arguments}} for call in message.tool_calls
            ]
        if message.tool_name:
            row["tool_name"] = message.tool_name
        rows.append(row)
    return rows


def _reply(data: object, max_tokens: int, context_length: int) -> ModelReply:
    """Parse a native reply and generate IDs when Ollama omits them."""
    validated = _Response.model_validate(data)
    if validated.done_reason == "length":
        if (
            validated.prompt_eval_count is not None
            and validated.eval_count is not None
            and validated.eval_count < max_tokens
            and validated.prompt_eval_count + validated.eval_count >= context_length
        ):
            raise DockSightError(
                "model_context_limit",
                "Model context window is full; reduce input or increase its size",
                ErrorKind.DEPENDENCY,
            )
        raise DockSightError("model_truncated", "Model output exceeded its token limit", ErrorKind.DEPENDENCY)
    calls = tuple(
        ToolCall(raw.id or f"call_{uuid4().hex}", raw.function.name, parse_object(raw.function.arguments))
        for raw in validated.message.tool_calls
    )
    return ModelReply(
        validated.message.content,
        calls,
        input_tokens=validated.prompt_eval_count,
        output_tokens=validated.eval_count,
    )


class OllamaModel:
    """Implement the model port through Ollama's native chat API."""

    def __init__(
        self, client: httpx.AsyncClient, model: str, max_tokens: int = 4096, context_length: int = 16384
    ) -> None:
        """Bind the client and explicit generation and context limits."""
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.context_length = context_length

    async def complete(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec] = (),
        schema: JsonObject | None = None,
    ) -> ModelReply:
        """Request native tool calls or schema output with thinking disabled."""
        body: dict[str, Any] = {
            "model": self.model,
            "messages": _messages(messages),
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "num_predict": self.max_tokens, "num_ctx": self.context_length},
        }
        if schema is not None:
            body["format"] = schema
            body["messages"].append(
                {
                    "role": "user",
                    "content": "Return only JSON matching this schema. Follow its field descriptions. "
                    "Keep the response language requested earlier.\n" + json.dumps(schema, ensure_ascii=False),
                }
            )
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools
            ]
        try:
            response = await self.client.post("/api/chat", json=body)
            if response.is_error:
                raise provider_error(response.status_code)
            return _reply(response.json(), self.max_tokens, self.context_length)
        except httpx.TimeoutException as exc:
            raise DockSightError("provider_timeout", "Model provider timed out", ErrorKind.TIMEOUT) from exc
        except httpx.HTTPError as exc:
            raise DockSightError(
                "provider_unavailable", "Model provider is unavailable", ErrorKind.UNAVAILABLE
            ) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise DockSightError(
                "invalid_model_response", "Model provider returned an invalid response", ErrorKind.DEPENDENCY
            ) from exc
