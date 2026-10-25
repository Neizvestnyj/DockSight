from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from docksight.domain.actions import ActionState, Operation
from docksight.domain.diagnostics import EvidenceRef
from docksight.domain.runtime import ContainerSnapshot, LogBatch, StackSummary


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WidgetProposal(Contract):
    widget_type: Literal["container_status", "log_anomalies", "compose_stack", "env_inspector"]
    evidence_ids: list[str] = Field(min_length=1, max_length=10)
    action: Operation | None = None

    @model_validator(mode="after")
    def check_action(self) -> Self:
        if self.action and self.widget_type != "container_status":
            raise ValueError("Actions belong to container status cards")

        return self


class DiagnosisProposal(Contract):
    summary: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(max_length=20)
    uncertain: bool
    widgets: list[WidgetProposal] = Field(max_length=8)

    @model_validator(mode="after")
    def check_evidence(self) -> Self:
        if not self.uncertain and not self.evidence_ids:
            raise ValueError("A confident diagnosis requires evidence")

        return self


class ActionView(Contract):
    id: str
    host: str
    container_id: str
    operation: Operation
    expires_at: datetime
    state: ActionState
    message: str
    confirmation_required: Literal[True] = True


class ContainerStatusCard(Contract):
    widget_type: Literal["container_status"] = "container_status"
    snapshot: ContainerSnapshot
    evidence_ids: list[str]
    actions: list[ActionView] = Field(default_factory=list[ActionView])


class LogAnomalyCard(Contract):
    widget_type: Literal["log_anomalies"] = "log_anomalies"
    host: str
    container_id: str
    logs: LogBatch
    evidence_ids: list[str]


class ComposeStackCard(Contract):
    widget_type: Literal["compose_stack"] = "compose_stack"
    host: str
    stacks: list[StackSummary]
    evidence_ids: list[str]


class EnvInspectorCard(Contract):
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
    schema_version: Literal[1] = 1
    summary: str
    uncertain: bool
    evidence: list[EvidenceRef]
    widgets: list[Widget]
