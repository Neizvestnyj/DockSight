from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from docksight.adapters.inbound.http.auth import HttpAuthentication, authenticated_principal
from docksight.adapters.inbound.http.schemas import (
    ActorWorkspaceInput,
    InvestigationCreate,
    InvestigationDetail,
    InvestigationWorkspaceInput,
    TurnInput,
)
from docksight.adapters.inbound.http.streaming import SnapshotResponse, authorized_observation
from docksight.application.investigations.contracts import (
    AcceptedTurn,
    ActorWorkspace,
    InvestigationPage,
    InvestigationView,
    InvestigationWorkspace,
    SavedTurn,
    TurnPage,
)
from docksight.application.investigations.runner import TurnRunner
from docksight.application.investigations.service import Investigations


def actor(request: Request) -> str:
    """Read the shared authenticated actor without accepting caller identity fields."""
    return request.state.actor


type Actor = Annotated[str, Depends(actor)]
type PageLimit = Annotated[int, Query(ge=1, le=50)]
type Cursor = Annotated[str | None, Query(min_length=1, max_length=1024)]


def build_investigations_router(history: Investigations, runner: TurnRunner, auth: HttpAuthentication) -> APIRouter:
    """Bind actor-scoped archive operations and observation without generating on reads."""
    router = APIRouter(prefix="/api/v1", tags=["Investigations"], dependencies=[Depends(authenticated_principal)])

    @router.get("/me/workspace")
    async def workspace(actor: Actor) -> ActorWorkspace:
        """Restore acknowledged actor preferences independently of current configuration."""
        return await history.workspace(actor)

    @router.patch("/me/workspace")
    async def patch_actor(patch: ActorWorkspaceInput, actor: Actor) -> ActorWorkspace:
        """Validate and compare actor preferences before acknowledging them."""
        return await history.patch_actor_workspace(actor, patch)

    @router.post("/investigations", status_code=201)
    async def create(value: InvestigationCreate, actor: Actor) -> InvestigationView:
        """Create the exact requested UUID within the actor's configured host scope."""
        return await history.create(actor, str(value.id), value.host)

    @router.get("/investigations")
    async def listing(actor: Actor, limit: PageLimit = 10, before: Cursor = None) -> InvestigationPage:
        """Return owned activity keysets without interpreting initial page size as retention."""
        return await history.list_owned(actor, limit, before)

    @router.get("/investigations/{investigation_id}")
    async def detail(investigation_id: UUID, actor: Actor) -> InvestigationDetail:
        """Restore owned metadata, acknowledged workspace, and newest display turns."""
        saved, turns = await history.snapshot(actor, str(investigation_id))
        return InvestigationDetail(**saved.model_dump(), turns=turns)

    @router.get("/investigations/{investigation_id}/turns")
    async def turns(investigation_id: UUID, actor: Actor, limit: PageLimit = 20, before: Cursor = None) -> TurnPage:
        """Page older owned immutable snapshots in display order."""
        return await history.turns(actor, str(investigation_id), limit, before)

    @router.patch("/investigations/{investigation_id}/workspace")
    async def patch_workspace(
        investigation_id: UUID,
        patch: InvestigationWorkspaceInput,
        actor: Actor,
    ) -> InvestigationWorkspace:
        """Save only supplied workspace fields after optimistic revision validation."""
        return await history.patch_workspace(actor, str(investigation_id), patch)

    @router.delete("/investigations/{investigation_id}", status_code=204)
    async def delete(investigation_id: UUID, actor: Actor) -> Response:
        """Delete owned inactive history while preserving actions and execution protection."""
        await history.delete(actor, str(investigation_id))
        return Response(status_code=204)

    @router.post("/investigations/{investigation_id}/turns", status_code=202)
    async def submit(investigation_id: UUID, value: TurnInput, request: Request, actor: Actor) -> AcceptedTurn:
        """Return only after the receipt commits and its retained worker is registered."""
        return await runner.submit(actor, value.command(investigation_id), request.state.request_id)

    @router.get("/turns/{turn_id}")
    async def turn(turn_id: UUID, actor: Actor) -> SavedTurn:
        """Read the authoritative saved revision without preparing actions or generating."""
        return await history.archive.read_turn(actor, str(turn_id))

    @router.get("/turns/{turn_id}/events", response_class=SnapshotResponse, response_model=None)
    async def observe(turn_id: UUID, request: Request, actor: Actor) -> SnapshotResponse:
        """Attach a bounded observer after checking ownership and capacity before response headers."""
        source, initial = await authorized_observation(runner, actor, str(turn_id))
        return SnapshotResponse(source, initial, auth, request, actor)

    @router.post("/turns/{turn_id}/cancel")
    async def cancel(turn_id: UUID, actor: Actor) -> SavedTurn:
        """Explicitly stop accepted work and return its persisted terminal winner."""
        return await runner.cancel(actor, str(turn_id))

    return router
