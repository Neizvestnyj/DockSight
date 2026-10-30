from typing import Literal, TypedDict

from docksight.domain.diagnostics import JsonObject


class TurnStarted(TypedDict):
    """Announce the leased session and new diagnostic turn."""

    type: Literal["turn.started"]
    turn_id: str
    session_id: str


class TraceStarted(TypedDict):
    """Identify public model configuration and the server start time for this turn's trace."""

    type: Literal["trace.started"]
    turn_id: str
    provider: str | None
    model: str | None
    started_at: str


class TraceStepEvent(TypedDict):
    """Insert or replace one bounded, sanitized diagnostic step by its application-issued ID."""

    type: Literal["trace.step"]
    turn_id: str
    step: JsonObject


class ToolStarted(TypedDict):
    """Announce a model-selected read-only tool before execution."""

    type: Literal["tool.started"]
    turn_id: str
    tool: str


class ToolCompleted(TypedDict):
    """Report completion or a safe failure of one tool call."""

    type: Literal["tool.completed"]
    turn_id: str
    tool: str
    ok: bool


class AnswerReady(TypedDict):
    """Carry the validated answer and server-assembled cards."""

    type: Literal["answer.ready"]
    turn_id: str
    answer: JsonObject


class ClarificationRequired(TypedDict):
    """Finish discovery with server-verified group choices instead of a diagnostic answer."""

    type: Literal["clarification.required"]
    turn_id: str
    selection: JsonObject


class TurnCompleted(TypedDict):
    """Mark a diagnostic turn as successfully finished."""

    type: Literal["turn.completed"]
    turn_id: str


class TurnFailed(TypedDict):
    """Terminate a diagnostic turn with a safe public error."""

    type: Literal["turn.failed"]
    turn_id: str
    code: str
    message: str


type TurnEvent = (
    TurnStarted
    | TraceStarted
    | TraceStepEvent
    | ToolStarted
    | ToolCompleted
    | AnswerReady
    | ClarificationRequired
    | TurnCompleted
    | TurnFailed
)
