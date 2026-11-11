from collections.abc import AsyncGenerator
from typing import cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Request

from docksight.adapters.inbound.http.auth import HttpAuthentication
from docksight.adapters.inbound.http.schemas import ChatTurn
from docksight.adapters.inbound.http.streaming import EventResponse, authorized_observation
from docksight.application.events import TurnEvent
from docksight.application.investigations.contracts import (
    AcceptedTurn,
    InvestigationView,
    QuestionTurn,
    SavedTurn,
    StartTurn,
)
from docksight.application.investigations.runner import TurnRunner
from docksight.application.investigations.service import Investigations
from docksight.application.views.schemas import ContainerTarget
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError, ErrorKind


async def accept_legacy(
    history: Investigations,
    runner: TurnRunner,
    value: ChatTurn,
    actor: str,
    request_id: str,
) -> AcceptedTurn:
    """Map old sessions to durable investigations and resolve receipts before mutable configuration."""
    submission_id = value.submission_id or uuid4()
    identity = value.session_id or uuid5(NAMESPACE_URL, f"docksight:{actor}:{submission_id}")
    command = StartTurn(
        QuestionTurn(
            investigation_id=str(identity),
            submission_id=str(submission_id),
            expected_revision=0,
            query=value.query,
            target=value.group
            or (ContainerTarget(id=value.container_id, name=value.container_id) if value.container_id else None),
            model=value.model_selection,
        )
    )
    prior = await runner.turns.submission(actor, str(submission_id), runner.digest(command))
    if prior is not None:
        if prior.host != value.host:
            raise DockSightError("session_not_found", "Session not found for this actor and host", ErrorKind.NOT_FOUND)
        return AcceptedTurn(snapshot=prior, created=False)
    view = await _legacy_view(history, value, actor, str(identity))
    command = StartTurn(command.root.model_copy(update={"expected_revision": view.workspace.revision}))
    return await runner.submit(actor, command, request_id)


async def _legacy_view(history: Investigations, value: ChatTurn, actor: str, identity: str) -> InvestigationView:
    """Preserve scoped legacy session errors while creating only explicitly new investigations."""
    if value.session_id is None:
        return await history.create(actor, identity, value.host)
    try:
        view = await history.read(actor, identity)
    except DockSightError as exc:
        if exc.kind != ErrorKind.NOT_FOUND:
            raise
        raise DockSightError("session_not_found", "Session not found for this actor and host", exc.kind) from exc
    if view.host != value.host:
        raise DockSightError("session_not_found", "Session not found for this actor and host", ErrorKind.NOT_FOUND)
    return view


async def legacy_events(source: AsyncGenerator[SavedTurn], initial: SavedTurn) -> AsyncGenerator[TurnEvent]:
    """Project committed revisions into old event shapes while owning only an observer."""
    projection = LegacyProjection()
    saved = initial
    try:
        yield {"type": "turn.started", "turn_id": initial.id, "session_id": initial.investigation_id}
        yield {
            "type": "trace.started",
            "turn_id": initial.id,
            "provider": initial.model.provider if initial.model else None,
            "model": initial.model.model if initial.model else None,
            "started_at": initial.created_at.isoformat(),
        }
        while True:
            for event in projection.changes(saved):
                yield event
            if saved.state != "running":
                for event in terminal_events(saved):
                    yield event
                return
            saved = await anext(source)
    finally:
        await source.aclose()


class LegacyProjection:
    """Coalesce repeated trace and progress values while preserving existing event payloads."""

    def __init__(self) -> None:
        """Retain only this observer's bounded public projection state."""
        self.traces: dict[str, object] = {}
        self.progress: dict[int, str] = {}

    def changes(self, saved: SavedTurn) -> list[TurnEvent]:
        """Emit trace replacements followed by changed tool progress from one committed revision."""
        events: list[TurnEvent] = []
        for step in saved.trace:
            if self.traces.get(step.id) != step:
                events.append(
                    {"type": "trace.step", "turn_id": saved.id, "step": cast(JsonObject, step.model_dump(mode="json"))}
                )
                self.traces[step.id] = step
        return events + self._progress(saved)

    def _progress(self, saved: SavedTurn) -> list[TurnEvent]:
        """Project only changed bounded tools, including completion coalesced with its start."""
        events: list[TurnEvent] = []
        for index, row in enumerate(saved.progress):
            if self.progress.get(index) == row.state:
                continue
            if row.state == "running":
                events.append({"type": "tool.started", "turn_id": saved.id, "tool": row.tool})
            else:
                events.append(
                    {"type": "tool.completed", "turn_id": saved.id, "tool": row.tool, "ok": row.state == "succeeded"}
                )
            self.progress[index] = row.state
        return events


def terminal_events(saved: SavedTurn) -> tuple[TurnEvent, ...]:
    """Release only persisted validated answers, selections, and terminal failures."""
    if saved.answer is not None:
        return (
            {
                "type": "answer.ready",
                "turn_id": saved.id,
                "answer": cast(JsonObject, saved.answer.model_dump(mode="json")),
            },
            {"type": "turn.completed", "turn_id": saved.id},
        )
    if saved.selection is not None:
        return (
            {
                "type": "clarification.required",
                "turn_id": saved.id,
                "selection": cast(JsonObject, saved.selection.model_dump(mode="json")),
            },
            {"type": "turn.completed", "turn_id": saved.id},
        )
    return (
        {
            "type": "turn.failed",
            "turn_id": saved.id,
            "code": saved.error.code if saved.error else f"turn_{saved.state}",
            "message": saved.error.message if saved.error else "Diagnostic did not complete",
        },
    )


def build_legacy_router(history: Investigations, runner: TurnRunner, auth: HttpAuthentication) -> APIRouter:
    """Retain old chat transport over the same durable admission and observation path."""
    router = APIRouter()

    @router.post(
        "/chat/turns",
        response_model=None,
        response_class=EventResponse,
        tags=["Chat"],
        responses={200: {"content": {"text/event-stream": {}}}},
    )
    async def chat(turn: ChatTurn, request: Request) -> EventResponse:
        """Accept before streaming and detach independently when the caller disconnects."""
        actor = request.state.actor
        try:
            accepted = await accept_legacy(history, runner, turn, actor, request.state.request_id)
        except DockSightError as exc:
            if exc.code != "session_not_found":
                raise
            return EventResponse(_legacy_failure(exc), request.state.request_id)
        source, initial = await authorized_observation(runner, actor, accepted.snapshot.id)
        return EventResponse(
            legacy_events(source, initial), initial.request_id, auth=auth, request=request, observer=source
        )

    return router


async def _legacy_failure(exc: DockSightError) -> AsyncGenerator[TurnEvent]:
    """Preserve the scoped-session failure frame for foreign or missing legacy sessions."""
    yield {"type": "turn.failed", "turn_id": "", "code": exc.code, "message": exc.message}
