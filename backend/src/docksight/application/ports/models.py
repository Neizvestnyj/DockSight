from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from docksight.domain.diagnostics import JsonObject


@dataclass(frozen=True)
class ToolSpec:
    """Describe an application-approved model tool and its argument schema."""

    name: str
    description: str
    parameters: JsonObject


@dataclass(frozen=True)
class ToolCall:
    """Identify a model-selected tool invocation and parsed arguments."""

    id: str
    name: str
    arguments: JsonObject


@dataclass(frozen=True)
class ModelMessage:
    """Carry provider-neutral conversation data with optional native replay items."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None
    native: tuple[JsonObject, ...] = ()


@dataclass(frozen=True)
class ModelReply:
    """Return normalized output, tool calls, replay data, and token usage."""

    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    native: tuple[JsonObject, ...] = ()
    input_tokens: int | None = None
    output_tokens: int | None = None


class ModelPort(Protocol):
    """Define provider-independent tool calling and structured final output."""

    async def complete(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec] = (),
        schema: JsonObject | None = None,
    ) -> ModelReply:
        """Produce a model reply using approved tools or the requested JSON schema."""
        ...
