from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from docksight.domain.actions import ActionState, Operation
from docksight.domain.diagnostics import EvidenceRef
from docksight.domain.runtime import ContainerSnapshot, LogBatch, StackSummary


class Contract(BaseModel):
    """Forbid unrecognized fields in application and HTTP data contracts."""

    model_config = ConfigDict(extra="forbid")


class GroupTarget(Contract):
    """Select one observed Compose project or Swarm stack on the current host."""

    kind: Literal["compose", "swarm"]
    name: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


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


class CauseAssessment(Contract):
    """Separate an evidence-backed immediate failure from deeper explanations and unknowns."""

    immediate: str = Field(min_length=1, max_length=600)
    underlying: str | None = Field(default=None, min_length=1, max_length=600)
    unknowns: list[Annotated[str, Field(min_length=1, max_length=240)]] = Field(default_factory=list, max_length=4)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)


class WidgetProposal(Contract):
    """Let a model select a widget and evidence without supplying runtime values."""

    widget_type: Literal["container_status", "log_anomalies", "compose_stack", "env_inspector"]
    evidence_ids: list[str] = Field(min_length=1, max_length=10)
    action: Operation | None = None
    action_reason: str | None = Field(default=None, min_length=1, max_length=240)

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
    recommendation: ActionRecommendation | None = None

    @model_validator(mode="after")
    def check_recommendation(self) -> Self:
        """Require the recommended ID to belong to this card's exact server-prepared target."""
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
    evidence: list[EvidenceRef]
    widgets: list[Widget]
