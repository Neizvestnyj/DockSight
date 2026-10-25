from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.security import HTTPBearer

from docksight.adapters.inbound.http.schemas import (
    ActionExecute,
    ActionPrepare,
    ChatTurn,
    ContainerId,
    HostId,
)
from docksight.adapters.inbound.http.streaming import EventResponse
from docksight.application.actions import Actions
from docksight.application.diagnostics.use_case import Diagnostics
from docksight.application.queries import RuntimeQueries
from docksight.application.views.registry import widget_schema
from docksight.application.views.schemas import ActionView
from docksight.domain.diagnostics import JsonObject
from docksight.domain.runtime import (
    ContainerSnapshot,
    Host,
    LogBatch,
    ResourceMetrics,
    StackSummary,
)


def build_router(queries: RuntimeQueries, diagnostics: Diagnostics, actions: Actions) -> APIRouter:
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(HTTPBearer())])

    @router.get("/hosts", tags=["Runtime"])
    async def hosts() -> tuple[Host, ...]:
        return queries.hosts()

    @router.get("/hosts/{host}/containers", tags=["Runtime"])
    async def containers(host: HostId) -> tuple[ContainerSnapshot, ...]:
        return await queries.containers(host)

    @router.get("/hosts/{host}/containers/{container_id}", tags=["Runtime"])
    async def inspect(host: HostId, container_id: ContainerId) -> ContainerSnapshot:
        return await queries.inspect(host, container_id)

    @router.get("/hosts/{host}/containers/{container_id}/logs", tags=["Runtime"])
    async def logs(
        host: HostId,
        container_id: ContainerId,
        lines: Annotated[int, Query(ge=1, le=queries.log_lines)] = queries.log_lines,
    ) -> LogBatch:
        return await queries.logs(host, container_id, lines)

    @router.get("/hosts/{host}/containers/{container_id}/stats", tags=["Runtime"])
    async def stats(host: HostId, container_id: ContainerId) -> ResourceMetrics:
        return await queries.stats(host, container_id)

    @router.get("/hosts/{host}/stacks", tags=["Runtime"])
    async def stacks(
        host: HostId, kind: Literal["compose", "swarm"] = "compose"
    ) -> tuple[StackSummary, ...]:
        return await queries.stacks(host, kind)

    @router.post("/actions", status_code=201, tags=["Actions"])
    async def prepare(action: ActionPrepare) -> ActionView:
        return await actions.prepare("operator", action.host, action.container_id, action.operation)

    @router.get("/actions/{action_id}", tags=["Actions"])
    async def action_state(action_id: UUID) -> ActionView:
        return await actions.get(str(action_id), "operator")

    @router.post("/actions/{action_id}/execute", tags=["Actions"])
    async def execute(
        action_id: UUID,
        confirmation: ActionExecute,
        idempotency_key: Annotated[str, Header(min_length=3, max_length=128)],
    ) -> ActionView:
        return await actions.execute(
            str(action_id), "operator", idempotency_key, confirmation.confirmed
        )

    @router.get("/widgets/schema", tags=["Schemas"])
    async def schema() -> JsonObject:
        return widget_schema()

    @router.post(
        "/chat/turns",
        response_model=None,
        response_class=EventResponse,
        tags=["Chat"],
        responses={200: {"content": {"text/event-stream": {}}}},
    )
    async def chat(turn: ChatTurn, request: Request) -> EventResponse:
        queries.check_host(turn.host)
        source = diagnostics.stream(
            "operator", turn.host, turn.query, str(turn.session_id) if turn.session_id else None
        )

        return EventResponse(source, request.state.request_id)

    return router
