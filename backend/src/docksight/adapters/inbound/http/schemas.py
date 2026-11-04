from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, RootModel, StrictBool, model_validator

from docksight.application.investigations.contracts import (
    ActorWorkspacePatch,
    InvestigationView,
    StartTurn,
    Target,
    TurnPage,
    WorkspacePatch,
)
from docksight.application.model_catalog import ModelSelection
from docksight.application.views.schemas import Contract, GroupTarget
from docksight.domain.actions import Operation

type HostId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
type ContainerId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")]


class ChatTurn(Contract):
    """Accept a diagnostic query scoped to one host and optional session."""

    host: HostId
    query: str = Field(min_length=1, max_length=4000)
    session_id: UUID | None = None
    submission_id: UUID | None = None
    group: GroupTarget | None = None
    container_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    model_selection: ModelSelection | None = None

    @model_validator(mode="after")
    def single_target(self) -> Self:
        """Reject conflicting explicit scopes rather than silently preferring one resource."""
        if self.group is not None and self.container_id is not None:
            raise ValueError("Choose either a group or an exact container")
        return self


class ActionPrepare(Contract):
    """Identify the exact container and operation to prepare."""

    host: HostId
    container_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    operation: Operation


class ActionExecute(Contract):
    """Carry the caller's explicit confirmation of a prepared action."""

    confirmed: StrictBool


class BrowserSessionInput(Contract):
    """Require an empty JSON object for browser login and logout."""


class BrowserSessionView(Contract):
    """Expose session-bound bootstrap authority without revealing the HttpOnly credential."""

    actor: str = Field(min_length=1, max_length=128)
    expires_at: AwareDatetime
    csrf_token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$", repr=False)


type Revision = Annotated[int, Field(strict=True, ge=0, le=9007199254740991)]


class InvestigationCreate(Contract):
    """Choose an idempotent client UUID and one configured host."""

    id: UUID
    host: HostId


class InvestigationDetail(InvestigationView):
    """Combine metadata and workspace with the newest display page."""

    turns: TurnPage


class InvestigationWorkspaceInput(WorkspacePatch):
    """Bound browser optimistic revisions before entering the application."""

    expected_revision: Revision


class ActorWorkspaceInput(ActorWorkspacePatch):
    """Bound independently revisioned actor preference writes."""

    expected_revision: Revision


class SubmissionInput(Contract):
    """Carry actor-independent immutable submission identity and admission revision."""

    submission_id: UUID
    expected_revision: Revision
    model: ModelSelection | None = None


class QuestionInput(SubmissionInput):
    """Submit a question and optional exact target without authoritative server IDs."""

    kind: Literal["question"]
    query: str = Field(min_length=1, max_length=4000)
    target: Target | None = None


class ClarificationInput(SubmissionInput):
    """Choose a persisted candidate without accepting a replacement question."""

    kind: Literal["clarification"]
    clarification_of: UUID
    expected_parent_revision: Revision
    target: Target


class TurnInput(RootModel[Annotated[QuestionInput | ClarificationInput, Field(discriminator="kind")]]):
    """Convert bounded transport UUIDs into the application-owned submission union."""

    def command(self, investigation_id: UUID) -> StartTurn:
        """Bind the route's authoritative archive identifier to submitted logical input."""
        return StartTurn.model_validate(self.root.model_dump(mode="json") | {"investigation_id": str(investigation_id)})
