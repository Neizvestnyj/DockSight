from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from docksight.application.events import TurnEvent
from docksight.application.investigations.contracts import (
    AcceptedTurn,
    ActorWorkspace,
    ActorWorkspacePatch,
    DiagnosticCommand,
    InvestigationPage,
    InvestigationView,
    InvestigationWorkspace,
    SavedTurn,
    StartTurn,
    TurnOutcome,
    TurnPage,
    TurnUpdate,
    WorkspacePatch,
)
from docksight.application.model_catalog import ModelSelection
from docksight.application.ports.models import ModelMessage


class InvestigationArchive(Protocol):
    """Own detached archive reads and explicit revisioned workspace writes."""

    async def create(self, actor: str, investigation_id: str, host: str, now: datetime) -> InvestigationView:
        """Create an owned archive or return its identical prior creation."""
        ...

    async def list_owned(self, actor: str, limit: int = 10, cursor: str | None = None) -> InvestigationPage:
        """List recent owned activity without expiring older archives."""
        ...

    async def read(self, actor: str, investigation_id: str) -> InvestigationView:
        """Read owned metadata and the acknowledged workspace."""
        ...

    async def snapshot(self, actor: str, investigation_id: str) -> tuple[InvestigationView, TurnPage]:
        """Read owned metadata and its initial display page from one archive snapshot."""
        ...

    async def turns(self, actor: str, investigation_id: str, limit: int = 20, cursor: str | None = None) -> TurnPage:
        """Return bounded chronological turn pages scoped to this actor and investigation."""
        ...

    async def read_turn(self, actor: str, turn_id: str) -> SavedTurn:
        """Read one validated owned snapshot or a typed unsupported-history failure."""
        ...

    async def patch_workspace(
        self, actor: str, investigation_id: str, patch: WorkspacePatch, now: datetime
    ) -> InvestigationWorkspace:
        """Apply explicit draft and selection changes using revision compare-and-swap."""
        ...

    async def workspace(self, actor: str) -> ActorWorkspace:
        """Read actor preferences, including an unpersisted revision-zero default."""
        ...

    async def patch_actor_workspace(self, actor: str, patch: ActorWorkspacePatch, now: datetime) -> ActorWorkspace:
        """Apply explicit preferences and validate any owned last-active reference."""
        ...

    async def delete(self, actor: str, investigation_id: str, now: datetime) -> None:
        """Delete inactive owned content while retaining execution protection and receipts."""
        ...


class TurnStore(Protocol):
    """Separate durable diagnostic admission and lifecycle from archive browsing."""

    async def submission(self, actor: str, submission_id: str, input_digest: str) -> SavedTurn | None:
        """Resolve actor-scoped receipts before mutable validation and preserve deletion tombstones."""
        ...

    async def accept(
        self, actor: str, command: StartTurn, input_digest: str, request_id: str, now: datetime
    ) -> AcceptedTurn:
        """Atomically reserve capacity and scope using a redacted command and pre-redaction digest."""
        ...

    async def update(self, actor: str, turn_id: str, update: TurnUpdate, now: datetime) -> SavedTurn:
        """Commit bounded progress before notifying observers."""
        ...

    async def finish(self, actor: str, turn_id: str, outcome: TurnOutcome, now: datetime) -> SavedTurn:
        """Commit one terminal result, bounded context, and released reservations atomically."""
        ...

    async def context(self, actor: str, investigation_id: str) -> tuple[ModelMessage, ...]:
        """Read only retained plain successful-question and validated-summary pairs."""
        ...


class DiagnosticLease(Protocol):
    """Own one shared capacity reservation and its monotonic diagnostic deadline."""

    deadline: float

    def run(self, command: DiagnosticCommand) -> AsyncGenerator[TurnEvent]:
        """Run once using the already-held slot without a second capacity acquisition."""
        ...

    async def close(self) -> None:
        """Release the reserved slot exactly once after diagnostic cleanup."""
        ...


class DiagnosticSource(Protocol):
    """Reserve global diagnostic capacity after model selection and before acceptance."""

    async def reserve(self) -> DiagnosticLease:
        """Reject exhausted capacity and return an independently owned reservation."""
        ...


@dataclass(frozen=True)
class SelectedDiagnostics:
    """Bind a configured validated selection to its shared-capacity diagnostic source."""

    diagnostics: DiagnosticSource
    identity: ModelSelection | None
