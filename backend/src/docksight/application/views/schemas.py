import re
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from docksight.domain.actions import ActionState, Operation
from docksight.domain.diagnostics import EvidenceRef
from docksight.domain.runtime import ContainerHealth, ContainerSnapshot, ContainerState, LogBatch, StackSummary


def _readable_explanation(value: str) -> None:
    """Reject placeholders and reference-only text without imposing a language or translating observations."""
    text = re.sub(r"\be\d+\b", "", value.strip(), flags=re.I)
    if (
        not any(character.isalpha() for character in text)
        or text.casefold() in {"null", "none", "n/a", "undefined"}
        or re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", text)
    ):
        raise ValueError(
            "An explanation must contain human-readable prose, not evidence IDs, placeholders, or machine codes"
        )


class Contract(BaseModel):
    """Forbid unrecognized fields in application and HTTP data contracts."""

    model_config = ConfigDict(extra="forbid")


class GroupTarget(Contract):
    """Select one observed Compose project or Swarm stack on the current host."""

    kind: Literal["compose", "swarm"]
    name: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


class GroupSelection(Contract):
    """Ask the operator to select from distinct observed groups on the current host."""

    candidates: list[GroupTarget] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_candidates(self) -> Self:
        """Keep repeated options from implying independent observed resources."""
        if len({(row.kind, row.name) for row in self.candidates}) != len(self.candidates):
            raise ValueError("Group candidates must be distinct")
        return self


class ContainerTarget(Contract):
    """Identify one observed container independently of an identically named group."""

    kind: Literal["container"] = "container"
    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    name: str = Field(min_length=1, max_length=256)


class TargetSelection(Contract):
    """Offer distinct observed containers and groups without guessing across resource namespaces."""

    candidates: list[Annotated[GroupTarget | ContainerTarget, Field(discriminator="kind")]] = Field(
        min_length=1, max_length=32
    )

    @model_validator(mode="after")
    def unique_candidates(self) -> Self:
        """Deduplicate containers by exact ID and groups by namespace and canonical name."""
        keys = {(row.kind, row.id if isinstance(row, ContainerTarget) else row.name) for row in self.candidates}
        if len(keys) != len(self.candidates):
            raise ValueError("Target candidates must be distinct")
        return self


class GroupLogResult(Contract):
    """Report what was actually collected for a local problem container."""

    container_id: str
    name: str
    state: Literal["collected", "failed", "not_collected"]
    evidence_id: str | None = None
    code: str | None = None


class GroupInspection(Contract):
    """Keep server-owned member counts and bounded log coverage separate from model claims."""

    summary: StackSummary
    evidence_id: str
    logs: list[GroupLogResult] = Field(max_length=200)
    inventory_code: str | None = None


class HostMember(Contract):
    """Project a local container's observations without copying environment values into the overview."""

    container_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    name: str = Field(min_length=1, max_length=4096)
    state: ContainerState
    health: ContainerHealth | None
    exit_code: int
    oom_killed: bool
    restart_count: int = Field(ge=0)
    observed_at: datetime
    group: GroupTarget | None
    attention: bool


class HostInspection(Contract):
    """Keep observed local totals, bounded previews, and log coverage independent of model prose."""

    host: str = Field(min_length=1, max_length=64)
    evidence_id: str
    total: int = Field(ge=0, le=200)
    running: int = Field(ge=0, le=200)
    attention: int = Field(ge=0, le=200)
    truncated: bool
    discovery_code: str | None
    members: list[HostMember] = Field(max_length=32)
    targets: list[GroupTarget] = Field(max_length=32)
    logs: list[GroupLogResult] = Field(max_length=32)


class CauseAssessment(Contract):
    """Separate an evidence-backed immediate failure from deeper explanations and unknowns."""

    immediate: str = Field(
        min_length=1,
        max_length=600,
        description=(
            "Explain the immediate failure in natural language. Never put evidence IDs, JSON, or machine codes here."
        ),
    )
    underlying: str | None = Field(
        default=None,
        min_length=1,
        max_length=600,
        description="A supported deeper cause in natural language, or null when not established.",
    )
    unknowns: list[Annotated[str, Field(min_length=1, max_length=240)]] = Field(
        default_factory=list,
        max_length=4,
        description=(
            "Unresolved questions in natural language. Use an empty array when none remain; never the string []."
        ),
    )
    evidence_ids: list[str] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def readable_cause(self) -> Self:
        """Reject identifier-only explanations so the single repair can request useful prose."""
        for value in (self.immediate, self.underlying, *self.unknowns):
            if value is not None:
                _readable_explanation(value)
        return self


class WidgetProposal(Contract):
    """Let a model select a widget and evidence without supplying runtime values."""

    widget_type: Literal["container_status", "log_anomalies", "compose_stack", "env_inspector"]
    evidence_ids: list[str] = Field(
        min_length=1,
        max_length=10,
        description=(
            "Collected evidence for this card. Container, log, and env cards each reference one exact container."
        ),
    )
    action: Operation | None = Field(
        default=None, description="Only container_status may recommend an operation; otherwise null."
    )
    action_reason: str | None = Field(
        default=None,
        min_length=1,
        max_length=240,
        description="A reason only when container_status explicitly recommends an action. Null when action is null.",
    )

    @model_validator(mode="after")
    def check_action(self) -> Self:
        """Reject action proposals on widgets other than container status cards."""
        if self.action and self.widget_type != "container_status":
            raise ValueError("Actions belong to container status cards")
        if self.action_reason and self.action is None:
            raise ValueError("An action reason requires an explicit action proposal")

        return self


class DiagnosisProposal(Contract):
    """Bound model-authored narrative, evidence references, and requested widgets."""

    summary: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(max_length=20)
    uncertain: bool
    cause: CauseAssessment | None = None
    widgets: list[WidgetProposal] = Field(max_length=8)

    @model_validator(mode="after")
    def check_evidence(self) -> Self:
        """Require evidence for any diagnosis the model declares confident."""
        if not self.uncertain and not self.evidence_ids:
            raise ValueError("A confident diagnosis requires evidence")

        return self


class ActionView(Contract):
    """Expose an opaque prepared action that always requires explicit confirmation."""

    id: str
    host: str
    container_id: str
    operation: Operation
    expires_at: datetime
    state: ActionState
    message: str
    confirmation_required: Literal[True] = True


class ActionRecommendation(Contract):
    """Link a model suggestion to one exact server-prepared action without granting permission."""

    action_id: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, min_length=1, max_length=240)


class ContainerStatusCard(Contract):
    """Present an observed container snapshot and server-prepared actions."""

    widget_type: Literal["container_status"] = "container_status"
    snapshot: ContainerSnapshot
    evidence_ids: list[str]
    actions: list[ActionView] = Field(default_factory=list[ActionView])
    actions_code: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    recommendation: ActionRecommendation | None = None

    @model_validator(mode="after")
    def check_recommendation(self) -> Self:
        """Require the recommended ID to belong to this card's exact server-prepared target."""
        if self.actions_code and self.actions:
            raise ValueError("Unavailable actions must not expose executable IDs")
        if self.recommendation and not any(
            action.id == self.recommendation.action_id
            and action.host == self.snapshot.host
            and action.container_id == self.snapshot.id
            for action in self.actions
        ):
            raise ValueError("A recommendation must reference this card's prepared action")
        return self


class LogAnomalyCard(Contract):
    """Present bounded sanitized logs linked to their collected evidence."""

    widget_type: Literal["log_anomalies"] = "log_anomalies"
    host: str
    container_id: str
    logs: LogBatch
    evidence_ids: list[str]


class ComposeStackCard(Contract):
    """Present server-read Compose or Swarm summaries for a configured host."""

    widget_type: Literal["compose_stack"] = "compose_stack"
    host: str
    stacks: list[StackSummary]
    evidence_ids: list[str]


class EnvInspectorCard(Contract):
    """Present allowlisted environment variables as a read-only widget."""

    widget_type: Literal["env_inspector"] = "env_inspector"
    host: str
    container_id: str
    variables: dict[str, str]
    evidence_ids: list[str]
    read_only: Literal[True] = True


type Widget = Annotated[
    ContainerStatusCard | LogAnomalyCard | ComposeStackCard | EnvInspectorCard,
    Field(discriminator="widget_type"),
]


class DiagnosisResponse(Contract):
    """Return the versioned diagnosis with evidence and validated UI cards."""

    schema_version: Literal[1] = 1
    summary: str
    uncertain: bool
    cause: CauseAssessment | None = None
    group: GroupInspection | None = None
    host_overview: HostInspection | None = None
    evidence: list[EvidenceRef]
    widgets: list[Widget] = Field(max_length=16)
