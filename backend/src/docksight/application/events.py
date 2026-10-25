from typing import Literal, TypedDict

from docksight.domain.diagnostics import JsonObject


class TurnStarted(TypedDict):
    type: Literal["turn.started"]
    turn_id: str
    session_id: str


class ToolStarted(TypedDict):
    type: Literal["tool.started"]
    turn_id: str
    tool: str


class ToolCompleted(TypedDict):
    type: Literal["tool.completed"]
    turn_id: str
    tool: str
    ok: bool


class AnswerReady(TypedDict):
    type: Literal["answer.ready"]
    turn_id: str
    answer: JsonObject


class TurnCompleted(TypedDict):
    type: Literal["turn.completed"]
    turn_id: str


class TurnFailed(TypedDict):
    type: Literal["turn.failed"]
    turn_id: str
    code: str
    message: str


type TurnEvent = (
    TurnStarted | ToolStarted | ToolCompleted | AnswerReady | TurnCompleted | TurnFailed
)
