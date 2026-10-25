from typing import Literal, TypedDict

from docksight.domain.diagnostics import JsonObject


class TurnStarted(TypedDict):
    """Announce the leased session and new diagnostic turn."""

    type: Literal["turn.started"]
    turn_id: str
    session_id: str


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


type TurnEvent = TurnStarted | ToolStarted | ToolCompleted | AnswerReady | TurnCompleted | TurnFailed
