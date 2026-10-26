from collections.abc import Sequence
from typing import cast

from openai import APIStatusError, APITimeoutError, AsyncOpenAI, OpenAIError
from openai.types.responses import Response, ResponseInputParam, ResponseTextConfigParam, ToolParam

from docksight.adapters.outbound.models.common import parse_object, provider_error, strict_schema
from docksight.application.ports.models import ModelMessage, ModelReply, ToolCall, ToolSpec
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError


def _messages(messages: Sequence[ModelMessage]) -> list[JsonObject]:
    """Encode tool results and replay native Responses items without losing reasoning."""
    rows: list[JsonObject] = []
    for message in messages:
        if message.role == "assistant" and message.native:
            rows.extend(message.native)
        elif message.role == "tool":
            rows.append({"type": "function_call_output", "call_id": message.tool_call_id, "output": message.content})
        else:
            rows.append({"role": message.role, "content": message.content})
    return rows


def _reply(response: Response) -> ModelReply:
    """Reject incomplete or refused output and preserve replayable native items."""
    if response.status != "completed":
        raise DockSightError("model_incomplete", "Model response did not complete", 502)
    calls: list[ToolCall] = []
    for item in response.output:
        if item.type == "function_call":
            calls.append(ToolCall(item.call_id, item.name, parse_object(item.arguments)))
        if item.type == "message" and any(block.type == "refusal" for block in item.content):
            raise DockSightError("model_refusal", "Model declined this request", 422)
    return ModelReply(
        response.output_text,
        tuple(calls),
        tuple(parse_object(item.model_dump(mode="json", by_alias=True, exclude_none=True)) for item in response.output),
        response.usage.input_tokens if response.usage else 0,
        response.usage.output_tokens if response.usage else 0,
    )


class OpenAIModel:
    """Implement the model port with native Responses and preserved reasoning items."""

    def __init__(self, client: AsyncOpenAI, model: str, max_tokens: int = 4096) -> None:
        """Bind the Responses client, model name, and output token limit."""
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    async def complete(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec] = (),
        schema: JsonObject | None = None,
    ) -> ModelReply:
        """Request a native Responses reply without storage or automatic retries."""
        functions: list[JsonObject] = [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": strict_schema(tool.parameters),
                "strict": True,
            }
            for tool in tools
        ]
        text: JsonObject = {}
        if schema is not None:
            text["format"] = {
                "type": "json_schema",
                "name": "docksight_response",
                "schema": strict_schema(schema),
                "strict": True,
            }
        try:
            response = await self.client.responses.create(
                model=self.model,
                input=cast(ResponseInputParam, _messages(messages)),
                tools=cast(list[ToolParam], functions),
                text=cast(ResponseTextConfigParam, text),
                store=False,
                include=["reasoning.encrypted_content"],
                max_output_tokens=self.max_tokens,
                stream=False,
            )
            return _reply(response)
        except APIStatusError as exc:
            raise provider_error(exc.status_code) from exc
        except APITimeoutError as exc:
            raise DockSightError("provider_timeout", "Model provider timed out", 504) from exc
        except OpenAIError as exc:
            raise DockSightError("provider_unavailable", "Model provider is unavailable", 503) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise DockSightError("invalid_model_response", "Model provider returned an invalid response", 502) from exc
