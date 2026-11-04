from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response

from docksight.adapters.inbound.http.auth import HttpAuthentication, authenticated_principal
from docksight.adapters.inbound.http.legacy import build_legacy_router
from docksight.adapters.inbound.http.schemas import (
    ActionExecute,
    ActionPrepare,
    ContainerId,
    HostId,
)
from docksight.application.actions import Actions
from docksight.application.investigations.runner import TurnRunner
from docksight.application.investigations.service import Investigations
from docksight.application.model_catalog import CatalogView, ModelSelection, ProvidersView
from docksight.application.model_choices import ModelChoices
from docksight.application.queries import RuntimeQueries
from docksight.application.system_status import SystemStatus, SystemStatusView
from docksight.application.views.registry import widget_schema
from docksight.application.views.schemas import ActionView
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError, ErrorKind
from docksight.domain.runtime import (
    ContainerSnapshot,
    Host,
    LogBatch,
    ResourceMetrics,
    StackSummary,
)


def _actor(request: Request) -> str:
    """Return the actor selected by the shared bearer-first principal resolver."""
    return request.state.actor


type Actor = Annotated[str, Depends(_actor)]


def build_router(
    queries: RuntimeQueries,
    actions: Actions,
    status: SystemStatus,
    history: Investigations,
    runner: TurnRunner,
    auth: HttpAuthentication,
    models: ModelChoices | None = None,
) -> APIRouter:
    """Bind versioned HTTP endpoints to application use cases."""
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticated_principal)])

    @router.get("/system/status", tags=["System"])
    async def system_status(
        request: Request,
        response: Response,
        host: HostId | None = None,
        provider: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
        model: Annotated[str | None, Query(min_length=1, max_length=256)] = None,
    ) -> SystemStatusView:
        """Check configured dependencies without generation or exposing private endpoints."""
        response.headers["Cache-Control"] = "no-store"
        if host is not None:
            queries.check_host(host)
        selected = await _selected_status(status, models, provider, model)
        return await selected.check(host, request.state.request_id)

    @router.get("/model-providers", tags=["Models"])
    async def model_providers(response: Response) -> ProvidersView:
        """Expose safe configured providers without fetching their model catalogs."""
        response.headers["Cache-Control"] = "no-store"
        if models is None:
            raise DockSightError("provider_not_configured", "Model selection is not configured", ErrorKind.UNAVAILABLE)
        return models.providers

    @router.get("/model-providers/{provider}/models", tags=["Models"])
    async def provider_models(
        provider: Annotated[str, Path(min_length=1, max_length=32)],
        response: Response,
        refresh: bool = False,
    ) -> CatalogView:
        """Return bounded lazy metadata with explicit freshness and failure state."""
        response.headers["Cache-Control"] = "no-store"
        if models is None:
            raise DockSightError("provider_not_configured", "Model selection is not configured", ErrorKind.UNAVAILABLE)
        return await models.catalog(provider, refresh)

    @router.get("/hosts", tags=["Runtime"])
    async def hosts() -> tuple[Host, ...]:
        """Return the configured host inventory."""
        return queries.hosts()

    @router.get("/hosts/{host}/containers", tags=["Runtime"])
    async def containers(host: HostId) -> tuple[ContainerSnapshot, ...]:
        """Read bounded container snapshots from one configured host."""
        return await queries.containers(host)

    @router.get("/hosts/{host}/containers/{container_id}", tags=["Runtime"])
    async def inspect(host: HostId, container_id: ContainerId) -> ContainerSnapshot:
        """Read a sanitized snapshot for the requested container."""
        return await queries.inspect(host, container_id)

    @router.get("/hosts/{host}/containers/{container_id}/logs", tags=["Runtime"])
    async def logs(
        host: HostId,
        container_id: ContainerId,
        lines: Annotated[int, Query(ge=1, le=queries.log_lines)] = queries.log_lines,
    ) -> LogBatch:
        """Read sanitized logs within configured line and byte limits."""
        return await queries.logs(host, container_id, lines)

    @router.get("/hosts/{host}/containers/{container_id}/stats", tags=["Runtime"])
    async def stats(host: HostId, container_id: ContainerId) -> ResourceMetrics:
        """Read current runtime metrics for one container."""
        return await queries.stats(host, container_id)

    @router.get("/hosts/{host}/stacks", tags=["Runtime"])
    async def stacks(host: HostId, kind: Literal["compose", "swarm"] = "compose") -> tuple[StackSummary, ...]:
        """Read Compose groups or Swarm service summaries."""
        return await queries.stacks(host, kind)

    @router.post("/actions", status_code=201, tags=["Actions"])
    async def prepare(action: ActionPrepare, actor: Actor) -> ActionView:
        """Prepare an expiring action bound to the authenticated actor."""
        return await actions.prepare(actor, action.host, action.container_id, action.operation)

    @router.get("/actions/{action_id}", tags=["Actions"])
    async def action_state(action_id: UUID, actor: Actor) -> ActionView:
        """Read an action only within the authenticated actor's scope."""
        return await actions.get(str(action_id), actor)

    @router.post("/actions/{action_id}/execute", tags=["Actions"])
    async def execute(
        action_id: UUID,
        confirmation: ActionExecute,
        idempotency_key: Annotated[str, Header(min_length=3, max_length=128)],
        actor: Actor,
    ) -> ActionView:
        """Execute a confirmed action using the supplied idempotency key."""
        return await actions.execute(str(action_id), actor, idempotency_key, confirmation.confirmed)

    @router.get("/widgets/schema", tags=["Schemas"])
    async def schema() -> JsonObject:
        """Return the selected widget's versioned JSON schema."""
        return widget_schema()

    router.include_router(build_legacy_router(history, runner, auth))

    return router


async def _selected_status(
    status: SystemStatus,
    models: ModelChoices | None,
    provider: str | None,
    model: str | None,
) -> SystemStatus:
    """Validate paired optional query fields before resolving a selection-specific probe."""
    if provider is None and model is None:
        return status
    if provider is None or model is None or models is None:
        raise DockSightError(
            "invalid_model_selection", "Provider and model must be selected together", ErrorKind.VALIDATION
        )
    _, probe = await models.select(ModelSelection(provider=provider, model=model))
    return status.with_model(probe, provider, model)
