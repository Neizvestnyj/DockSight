from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import httpx

from docksight.adapters.outbound.models.common import parse_object, provider_error
from docksight.application.ports.models import ModelMessage, ModelReply, ToolCall, ToolSpec
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError


class OllamaModel:
    def __init__(self, client: httpx.AsyncClient, model: str, max_tokens: int = 4096) -> None:
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    async def complete(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec] = (),
        schema: JsonObject | None = None,
    ) -> ModelReply:
        rows: list[dict[str, Any]] = []
        for message in messages:
            row: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.tool_calls:
                row["tool_calls"] = [
                    {"function": {"name": call.name, "arguments": call.arguments}}
                    for call in message.tool_calls
                ]
            if message.tool_name:
                row["tool_name"] = message.tool_name
            rows.append(row)
        body: dict[str, Any] = {
            "model": self.model,
            "messages": rows,
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "num_predict": self.max_tokens},
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
            data: dict[str, Any] = response.json()
            if data.get("done_reason") == "length":
                raise DockSightError(
                    "model_truncated", "Model output exceeded its token limit", 502
                )
            message_data: dict[str, Any] = data["message"]
            calls: list[ToolCall] = []
            raw_calls: list[dict[str, Any]] = message_data.get("tool_calls") or []
            for raw in raw_calls:
                calls.append(
                    ToolCall(
                        raw.get("id") or f"call_{uuid4().hex}",
                        raw["function"]["name"],
                        parse_object(raw["function"]["arguments"]),
                    )
                )

            return ModelReply(
                str(message_data.get("content") or ""),
                tuple(calls),
                input_tokens=int(data.get("prompt_eval_count", 0)),
                output_tokens=int(data.get("eval_count", 0)),
            )
        except httpx.TimeoutException as exc:
            raise DockSightError("provider_timeout", "Model provider timed out", 504) from exc
        except httpx.HTTPError as exc:
            raise DockSightError(
                "provider_unavailable", "Model provider is unavailable", 503
            ) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise DockSightError(
                "invalid_model_response", "Model provider returned an invalid response", 502
            ) from exc
