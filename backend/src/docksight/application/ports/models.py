from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from docksight.domain.diagnostics import JsonObject


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: JsonObject


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: JsonObject


@dataclass(frozen=True)
class ModelMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None
    native: tuple[JsonObject, ...] = ()


@dataclass(frozen=True)
class ModelReply:
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    native: tuple[JsonObject, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0


class ModelPort(Protocol):
    async def complete(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec] = (),
        schema: JsonObject | None = None,
    ) -> ModelReply: ...
