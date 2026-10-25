from collections.abc import Awaitable, Callable

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.views.schemas import (
    ActionView,
    ComposeStackCard,
    ContainerStatusCard,
    DiagnosisProposal,
    DiagnosisResponse,
    EnvInspectorCard,
    LogAnomalyCard,
    Widget,
)
from docksight.domain.actions import Operation
from docksight.domain.errors import DockSightError

type PrepareAction = Callable[[str, str, str, Operation], Awaitable[ActionView]]


class ViewAssembler:
    def __init__(self, prepare: PrepareAction | None = None) -> None:
        self.prepare = prepare

    async def build(
        self, proposal: DiagnosisProposal, context: EvidenceContext, actor: str
    ) -> DiagnosisResponse:
        references = list(
            dict.fromkeys(
                [
                    *proposal.evidence_ids,
                    *(ref for card in proposal.widgets for ref in card.evidence_ids),
                ]
            )
        )
        if any(ref not in context.evidence for ref in references):
            raise DockSightError("invalid_evidence", "Diagnosis references unknown evidence", 502)
        widgets: list[Widget] = []
        for card in proposal.widgets:
            refs = card.evidence_ids
            if card.widget_type == "compose_stack":
                ref = next((ref for ref in refs if ref in context.stacks), None)
                if ref is None:
                    raise DockSightError(
                        "invalid_evidence", "Stack card requires stack evidence", 502
                    )
                widgets.append(
                    ComposeStackCard(
                        host=context.evidence[ref].host,
                        stacks=list(context.stacks[ref]),
                        evidence_ids=refs,
                    )
                )
                continue
            snapshots = [context.snapshots[ref] for ref in refs if ref in context.snapshots]
            if not snapshots or len({(row.host, row.id) for row in snapshots}) != 1:
                raise DockSightError(
                    "invalid_evidence", "Card requires evidence for one exact container", 502
                )
            snapshot = snapshots[-1]
            if card.widget_type == "container_status":
                actions: list[ActionView] = []
                if self.prepare:
                    allowed: tuple[Operation, ...] = (
                        ("restart", "stop")
                        if snapshot.state == "running"
                        else ("restart",)
                        if snapshot.state in {"exited", "created"}
                        else ()
                    )
                    for operation in allowed:
                        actions.append(
                            await self.prepare(actor, snapshot.host, snapshot.id, operation)
                        )
                widgets.append(
                    ContainerStatusCard(snapshot=snapshot, evidence_ids=refs, actions=actions)
                )
            elif card.widget_type == "env_inspector":
                widgets.append(
                    EnvInspectorCard(
                        host=snapshot.host,
                        container_id=snapshot.id,
                        variables=dict(snapshot.environment),
                        evidence_ids=refs,
                    )
                )
            else:
                log_ref = next((ref for ref in refs if ref in context.logs), None)
                if log_ref is None:
                    raise DockSightError("invalid_evidence", "Log card requires log evidence", 502)
                widgets.append(
                    LogAnomalyCard(
                        host=snapshot.host,
                        container_id=snapshot.id,
                        logs=context.logs[log_ref],
                        evidence_ids=refs,
                    )
                )

        return DiagnosisResponse(
            summary=proposal.summary,
            uncertain=proposal.uncertain,
            evidence=[context.evidence[ref] for ref in references],
            widgets=widgets,
        )
