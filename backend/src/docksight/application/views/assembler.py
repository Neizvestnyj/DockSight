from collections.abc import Awaitable, Callable

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.views.schemas import (
    ActionRecommendation,
    ActionView,
    ComposeStackCard,
    ContainerStatusCard,
    DiagnosisProposal,
    DiagnosisResponse,
    EnvInspectorCard,
    LogAnomalyCard,
    Widget,
    WidgetProposal,
)
from docksight.domain.actions import Operation, allowed_operations
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import ContainerSnapshot

type PrepareAction = Callable[[str, str, str, Operation], Awaitable[ActionView]]


class ViewAssembler:
    """Build typed UI cards from collected evidence and server-owned action policies."""

    def __init__(self, prepare: PrepareAction | None = None) -> None:
        """Optionally bind action preparation for permitted container operations."""
        self.prepare = prepare

    async def build(self, proposal: DiagnosisProposal, context: EvidenceContext, actor: str) -> DiagnosisResponse:
        """Validate references and assemble cards without trusting model-supplied runtime values."""
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
        widgets = [await self._card(card, context, actor) for card in proposal.widgets]

        return DiagnosisResponse(
            summary=proposal.summary,
            uncertain=proposal.uncertain,
            evidence=[context.evidence[ref] for ref in references],
            widgets=widgets,
        )

    async def _card(self, card: WidgetProposal, context: EvidenceContext, actor: str) -> Widget:
        """Build a card using server-owned runtime values and prepared actions."""
        if card.widget_type == "compose_stack":
            return _stack_card(card.evidence_ids, context)
        snapshot = _container_snapshot(card.evidence_ids, context)
        if card.widget_type == "container_status":
            actions = await self._actions(actor, snapshot)
            suggested = next((action for action in actions if action.operation == card.action), None)
            return ContainerStatusCard(
                snapshot=snapshot,
                evidence_ids=card.evidence_ids,
                actions=actions,
                recommendation=ActionRecommendation(action_id=suggested.id, reason=card.action_reason)
                if suggested
                else None,
            )
        if card.widget_type == "env_inspector":
            return EnvInspectorCard(
                host=snapshot.host,
                container_id=snapshot.id,
                variables=dict(snapshot.environment),
                evidence_ids=card.evidence_ids,
            )
        ref = next((ref for ref in card.evidence_ids if ref in context.logs), None)
        if ref is None:
            raise DockSightError("invalid_evidence", "Log card requires log evidence", 502)
        return LogAnomalyCard(
            host=snapshot.host,
            container_id=snapshot.id,
            logs=context.logs[ref],
            evidence_ids=card.evidence_ids,
        )

    async def _actions(self, actor: str, snapshot: ContainerSnapshot) -> list[ActionView]:
        """Prepare only operations allowed for the observed container state."""
        if self.prepare is None:
            return []
        return [
            await self.prepare(actor, snapshot.host, snapshot.id, operation)
            for operation in allowed_operations(snapshot.state)
        ]


def _stack_card(refs: list[str], context: EvidenceContext) -> ComposeStackCard:
    """Require stack evidence before constructing a server-owned stack card."""
    ref = next((ref for ref in refs if ref in context.stacks), None)
    if ref is None:
        raise DockSightError("invalid_evidence", "Stack card requires stack evidence", 502)
    return ComposeStackCard(host=context.evidence[ref].host, stacks=list(context.stacks[ref]), evidence_ids=refs)


def _container_snapshot(refs: list[str], context: EvidenceContext) -> ContainerSnapshot:
    """Resolve card references to one exact container and use its latest snapshot."""
    snapshots = [row for ref, row in context.snapshots.items() if ref in refs]
    if not snapshots or len({(row.host, row.id) for row in snapshots}) != 1:
        raise DockSightError("invalid_evidence", "Card requires evidence for one exact container", 502)
    return max(enumerate(snapshots), key=lambda item: (item[1].observed_at, item[0]))[1]
