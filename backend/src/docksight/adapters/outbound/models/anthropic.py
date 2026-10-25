from collections.abc import Sequence
from typing import Any, cast

from anthropic import AnthropicError, APIStatusError, APITimeoutError, AsyncAnthropic
from anthropic.types import MessageParam, OutputConfigParam, ToolUnionParam

from docksight.adapters.outbound.models.common import parse_object, provider_error, strict_schema
from docksight.application.ports.models import ModelMessage, ModelReply, ToolCall, ToolSpec
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError


class AnthropicModel:
    def __init__(self, client: AsyncAnthropic, model: str, max_tokens: int = 4096) -> None:
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    async def complete(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec] = (),
        schema: JsonObject | None = None,
    ) -> ModelReply:
        system = "\n".join(message.content for message in messages if message.role == "system")
        rows: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                continue
            if message.role == "tool":
                rows.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.tool_call_id,
                                "content": message.content,
                            }
                        ],
                    }
                )
            elif message.role == "assistant" and message.native:
                rows.append({"role": "assistant", "content": list(message.native)})
            else:
                rows.append({"role": message.role, "content": message.content})
        functions: list[dict[str, Any]] = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": strict_schema(tool.parameters),
                "strict": True,
            }
            for tool in tools
        ]
        output: dict[str, Any] = {}
        if schema is not None:
            output["format"] = {"type": "json_schema", "schema": strict_schema(schema)}
        try:
            response = await self.client.messages.create(
                model=self.model,
                system=system,
                messages=cast(list[MessageParam], rows),
                tools=cast(list[ToolUnionParam], functions),
                output_config=cast(OutputConfigParam, output),
                max_tokens=self.max_tokens,
                stream=False,
            )
            if response.stop_reason == "refusal":
                raise DockSightError("model_refusal", "Model declined this request", 422)
            if response.stop_reason == "max_tokens":
                raise DockSightError(
                    "model_truncated", "Model output exceeded its token limit", 502
                )
            content = "".join(block.text for block in response.content if block.type == "text")
            calls = tuple(
                ToolCall(block.id, block.name, parse_object(block.input))
                for block in response.content
                if block.type == "tool_use"
            )

            return ModelReply(
                content,
                calls,
                tuple(parse_object(block.model_dump(mode="json")) for block in response.content),
                response.usage.input_tokens,
                response.usage.output_tokens,
            )
        except APIStatusError as exc:
            raise provider_error(exc.status_code) from exc
        except APITimeoutError as exc:
            raise DockSightError("provider_timeout", "Model provider timed out", 504) from exc
        except AnthropicError as exc:
            raise DockSightError(
                "provider_unavailable", "Model provider is unavailable", 503
            ) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise DockSightError(
                "invalid_model_response", "Model provider returned an invalid response", 502
            ) from exc
