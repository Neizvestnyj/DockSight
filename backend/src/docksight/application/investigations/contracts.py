from typing import Annotated, Final, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, RootModel, model_validator

from docksight.application.diagnostics.trace import TraceStep
from docksight.application.model_catalog import ModelSelection
from docksight.application.ports.models import ModelMessage
from docksight.application.views.schemas import ContainerTarget, DiagnosisResponse, GroupTarget, TargetSelection

type Identifier = Annotated[str, Field(pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")]
type Label = Annotated[str, Field(min_length=1, max_length=128)]
type Target = Annotated[GroupTarget | ContainerTarget, Field(discriminator="kind")]
type TurnState = Literal["running", "completed", "awaiting_selection", "failed", "stopped", "interrupted"]
SNAPSHOT_BYTES: Final = 2 * 1024 * 1024


class FrozenContract(BaseModel):
    """Reject unknown persisted fields and prevent reassignment of owned values."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class StorageLimits(FrozenContract):
    """Bound persisted history without automatic age-based eviction."""

    investigations_per_actor: int = Field(default=500, ge=1, le=500)
    turns_per_investigation: int = Field(default=200, ge=1, le=200)
    investigation_bytes: int = Field(default=32 * 1024 * 1024, ge=1, le=32 * 1024 * 1024)
    actor_bytes: int = Field(default=256 * 1024 * 1024, ge=1, le=256 * 1024 * 1024)
    snapshot_bytes: int = Field(default=SNAPSHOT_BYTES, ge=1, le=SNAPSHOT_BYTES)


class InvestigationWorkspace(FrozenContract):
    """Retain an acknowledged draft and exact selections with independent revision control."""

    revision: int = Field(default=0, ge=0)
    draft: str = Field(default="", max_length=8000)
    target: Target | None = None
    selected_container: ContainerTarget | None = None
    view: Literal["diagnostics", "containers"] = "diagnostics"


class WorkspacePatch(FrozenContract):
    """Apply only explicitly supplied fields after comparing the acknowledged revision."""

    expected_revision: int = Field(ge=0)
    draft: str = Field(default="", max_length=8000)
    target: Target | None = None
    selected_container: ContainerTarget | None = None
    view: Literal["diagnostics", "containers"] = "diagnostics"


class ActorWorkspace(FrozenContract):
    """Retain configured actor preferences without credentials or navigation side effects."""

    revision: int = Field(default=0, ge=0)
    last_investigation_id: Identifier | None = None
    host: Label | None = None
    model: ModelSelection | None = None


class ActorWorkspacePatch(FrozenContract):
    """Compare and replace explicitly supplied actor preferences."""

    expected_revision: int = Field(ge=0)
    last_investigation_id: Identifier | None = None
    host: Label | None = None
    model: ModelSelection | None = None


class InvestigationSummary(FrozenContract):
    """Identify saved actor-owned history without loading its complete turn archive."""

    id: Identifier
    host: Label
    title: str = Field(default="", max_length=120)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    active_turn_id: Identifier | None = None
    turn_count: int = Field(default=0, ge=0, le=200)


class InvestigationView(InvestigationSummary):
    """Return archive metadata and detached revisioned workspace values."""

    workspace: InvestigationWorkspace = Field(default_factory=InvestigationWorkspace)


class InvestigationPage(FrozenContract):
    """Return bounded activity-ordered summaries with an opaque continuation cursor."""

    items: tuple[InvestigationSummary, ...] = Field(max_length=50)
    next_cursor: str | None = Field(default=None, max_length=1024)


class TurnError(FrozenContract):
    """Persist only safe public error codes and messages."""

    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=512)


class TurnProgress(FrozenContract):
    """Record bounded read-only tool progress without arguments or raw output."""

    tool: str = Field(min_length=1, max_length=128)
    state: Literal["running", "succeeded", "failed"]


class SavedTurn(FrozenContract):
    """Own the versioned public turn snapshot independently of database schema revisions."""

    schema_version: Literal[1] = 1
    id: Identifier
    investigation_id: Identifier
    actor: Label
    host: Label
    submission_id: Identifier
    request_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=8000)
    target: Target | None = None
    model: ModelSelection | None = None
    clarification_of: Identifier | None = None
    resolved_by_turn_id: Identifier | None = None
    state: TurnState
    revision: int = Field(default=0, ge=0)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    progress: tuple[TurnProgress, ...] = Field(default=(), max_length=100)
    progress_truncated: bool = False
    trace: tuple[TraceStep, ...] = Field(default=(), max_length=133)
    answer: DiagnosisResponse | None = None
    selection: TargetSelection | None = None
    error: TurnError | None = None

    @model_validator(mode="after")
    def withhold_previews(self) -> Self:
        """Prevent persisted snapshots from retaining transient model output previews."""
        if any(step.response is not None or step.response_truncated for step in self.trace):
            raise ValueError("Saved trace previews must be omitted")
        return self


class UnsupportedTurn(FrozenContract):
    """Keep an unreadable item's identity visible without exposing or discarding its payload."""

    id: Identifier
    code: Literal["history_unsupported"] = "history_unsupported"


class TurnPage(FrozenContract):
    """Return older turn snapshots in chronological display order."""

    items: tuple[SavedTurn | UnsupportedTurn, ...] = Field(max_length=50)
    next_cursor: str | None = Field(default=None, max_length=1024)


class Submission(FrozenContract):
    """Carry immutable logical input and optimistic workspace admission metadata."""

    investigation_id: Identifier
    submission_id: Identifier
    expected_revision: int = Field(ge=0)
    model: ModelSelection | None = None


class QuestionTurn(Submission):
    """Submit a sanitized question with its explicit requested target."""

    kind: Literal["question"] = "question"
    query: str = Field(min_length=1, max_length=8000)
    target: Target | None = None


class ClarificationTurn(Submission):
    """Choose one parent candidate without replacing the original question."""

    kind: Literal["clarification"] = "clarification"
    clarification_of: Identifier
    expected_parent_revision: int = Field(ge=0)
    target: Target


class StartTurn(RootModel[Annotated[QuestionTurn | ClarificationTurn, Field(discriminator="kind")]]):
    """Validate distinct question and clarification submission envelopes."""

    model_config = ConfigDict(frozen=True)


class AcceptedTurn(FrozenContract):
    """Distinguish a newly committed turn from an existing submission receipt."""

    snapshot: SavedTurn
    created: bool


class TurnUpdate(FrozenContract):
    """Replace safe nonterminal observations at a compare-and-swap boundary."""

    expected_revision: int = Field(ge=0)
    progress: tuple[TurnProgress, ...] = Field(default=(), max_length=100)
    progress_truncated: bool = False
    trace: tuple[TraceStep, ...] = Field(default=(), max_length=133)


class TurnOutcome(FrozenContract):
    """Commit one terminal validated result before publishing it to observers."""

    expected_revision: int = Field(ge=0)
    state: Literal["completed", "awaiting_selection", "failed", "stopped", "interrupted"]
    answer: DiagnosisResponse | None = None
    selection: TargetSelection | None = None
    error: TurnError | None = None


class DiagnosticCommand(FrozenContract):
    """Bind preallocated IDs to sanitized input and bounded provider-neutral context."""

    turn_id: Identifier
    investigation_id: Identifier
    actor: Label
    host: Label
    query: str = Field(min_length=1, max_length=8000)
    target: Target | None = None
    identity: ModelSelection | None = None
    context: tuple[ModelMessage, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def plain_context(self) -> Self:
        """Exclude provider replay data and cap reconstructed history text."""
        if sum(len(message.content) for message in self.context) > 32000:
            raise ValueError("Context exceeds the supported text budget")
        if any(
            message.native or message.tool_calls or message.role not in {"user", "assistant"}
            for message in self.context
        ):
            raise ValueError("Context must contain plain question and summary messages")
        return self
