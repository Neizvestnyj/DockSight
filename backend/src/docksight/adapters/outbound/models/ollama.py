from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import httpx

from docksight.adapters.outbound.models.common import parse_object, provider_error
from docksight.application.ports.models import ModelMessage, ModelReply, ToolCall, ToolSpec
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError


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


def _reply(data: dict[str, Any]) -> ModelReply:
    """Parse a native reply and generate IDs when Ollama omits them."""
    if data.get("done_reason") == "length":
        raise DockSightError("model_truncated", "Model output exceeded its token limit", 502)
    message: dict[str, Any] = data["message"]
    raw_calls: list[dict[str, Any]] = message.get("tool_calls") or []
    calls = tuple(
        ToolCall(
            raw.get("id") or f"call_{uuid4().hex}", raw["function"]["name"], parse_object(raw["function"]["arguments"])
        )
        for raw in raw_calls
    )
    return ModelReply(
        str(message.get("content") or ""),
        calls,
        input_tokens=int(data.get("prompt_eval_count", 0)),
        output_tokens=int(data.get("eval_count", 0)),
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
            return _reply(response.json())
        except httpx.TimeoutException as exc:
            raise DockSightError("provider_timeout", "Model provider timed out", 504) from exc
        except httpx.HTTPError as exc:
            raise DockSightError("provider_unavailable", "Model provider is unavailable", 503) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise DockSightError("invalid_model_response", "Model provider returned an invalid response", 502) from exc
