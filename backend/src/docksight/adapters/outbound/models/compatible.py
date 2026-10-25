import json
from collections.abc import Sequence
from typing import Any, Literal, cast

from openai import APIStatusError, APITimeoutError, AsyncOpenAI, OpenAIError
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionToolChoiceOptionParam,
    ChatCompletionToolUnionParam,
)
from openai.types.shared_params import ResponseFormatJSONSchema, ResponseFormatText

from docksight.adapters.outbound.models.common import parse_object, provider_error, strict_schema
from docksight.application.ports.models import ModelMessage, ModelReply, ToolCall, ToolSpec
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError


class CompatibleModel:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        max_tokens: int = 4096,
        structured_output: Literal["native", "tool"] = "native",
    ) -> None:
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.structured_output = structured_output

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
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments),
                        },
                    }
                    for call in message.tool_calls
                ]
            if message.role == "tool":
                row["tool_call_id"] = message.tool_call_id
            rows.append(row)
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
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=cast(list[ChatCompletionMessageParam], rows),
                tools=cast(list[ChatCompletionToolUnionParam], functions),
                tool_choice=cast(ChatCompletionToolChoiceOptionParam, choice),
                response_format=cast(
                    ResponseFormatJSONSchema | ResponseFormatText, response_format
                ),
                max_tokens=self.max_tokens,
                temperature=0,
                stream=False,
            )
            item = response.choices[0]
            if item.finish_reason in {"length", "content_filter"}:
                raise DockSightError("model_incomplete", "Model response did not complete", 502)
            if item.message.refusal:
                raise DockSightError("model_refusal", "Model declined this request", 422)
            calls = tuple(
                ToolCall(call.id, call.function.name, parse_object(call.function.arguments))
                for call in item.message.tool_calls or []
                if call.type == "function"
            )
            content = item.message.content or ""
            if schema is not None and self.structured_output == "tool":
                if len(calls) != 1 or calls[0].name != "submit_diagnosis":
                    raise DockSightError(
                        "invalid_model_response", "Model did not submit a diagnosis", 502
                    )
                content = json.dumps(calls[0].arguments)
                calls = ()

            return ModelReply(
                content,
                calls,
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
            )
        except APIStatusError as exc:
            raise provider_error(exc.status_code) from exc
        except APITimeoutError as exc:
            raise DockSightError("provider_timeout", "Model provider timed out", 504) from exc
        except OpenAIError as exc:
            raise DockSightError(
                "provider_unavailable", "Model provider is unavailable", 503
            ) from exc
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise DockSightError(
                "invalid_model_response", "Model provider returned an invalid response", 502
            ) from exc
