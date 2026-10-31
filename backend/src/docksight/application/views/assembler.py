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
        cards = _target_cards(proposal.widgets, context)
        report = context.host_overview or context.group
        extra = [row.evidence_id for row in report.logs if row.evidence_id] if report else []
        if context.host_overview:
            extra.extend(context.evidence)
        references: list[str] = list(
            dict.fromkeys(
                [
                    *proposal.evidence_ids,
                    *(proposal.cause.evidence_ids if proposal.cause else []),
                    *([report.evidence_id] if report else []),
                    *extra,
                    *(ref for card in cards for ref in card.evidence_ids),
                ]
            )
        )
        if any(ref not in context.evidence for ref in references):
            raise DockSightError("invalid_evidence", "Diagnosis references unknown evidence", 502)
        widgets = [await self._card(card, context, actor) for card in cards]

        return DiagnosisResponse(
            summary=proposal.summary,
            uncertain=proposal.uncertain,
            cause=proposal.cause,
            group=context.group,
            host_overview=context.host_overview,
            evidence=[context.evidence[ref] for ref in references],
            widgets=widgets,
        )

    async def _card(self, card: WidgetProposal, context: EvidenceContext, actor: str) -> Widget:
        """Build a card using server-owned runtime values and prepared actions."""
        if card.widget_type == "compose_stack":
            return _stack_card(card.evidence_ids, context)
        snapshot = _container_snapshot(card.evidence_ids, context)
        if card.widget_type == "container_status":
            actions, actions_code = await self._actions(actor, snapshot)
            suggested = next((action for action in actions if action.operation == card.action), None)
            return ContainerStatusCard(
                snapshot=snapshot,
                evidence_ids=card.evidence_ids,
                actions=actions,
                actions_code=actions_code,
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

    async def _actions(self, actor: str, snapshot: ContainerSnapshot) -> tuple[list[ActionView], str | None]:
        """Keep observed facts usable when optional action preparation returns a typed failure."""
        if self.prepare is None:
            return [], None
        try:
            actions = [
                await self.prepare(actor, snapshot.host, snapshot.id, operation)
                for operation in allowed_operations(snapshot.state)
            ]
        except DockSightError as exc:
            return [], exc.code
        return actions, None


def _target_cards(proposed: list[WidgetProposal], context: EvidenceContext) -> list[WidgetProposal]:
    """Fill missing factual cards within response capacity while retaining model recommendations."""
    cards: list[WidgetProposal] = []
    for card in proposed:
        if card not in cards:
            cards.append(card)
    if context.container_id:
        log_ref = next(
            (ref for ref in context.logs if context.evidence[ref].container_id == context.container_id), None
        )
        _member_cards(cards, context, context.container_id, log_ref)
    if context.host_overview:
        _host_cards(cards, context)
        return cards
    report = context.group
    if report is None:
        return cards
    for member in report.logs[:4]:
        _member_cards(cards, context, member.container_id, member.evidence_id)
    return cards


def _host_cards(cards: list[WidgetProposal], context: EvidenceContext) -> None:
    """Include later host-scoped reads independently of the four automatic log candidates."""
    members: dict[str, str | None] = {}
    for ref, snapshot in context.snapshots.items():
        members.setdefault(snapshot.id, None)
        if ref in context.logs:
            members[snapshot.id] = ref
    for container_id, log_ref in members.items():
        _member_cards(cards, context, container_id, log_ref)


def _member_cards(
    cards: list[WidgetProposal], context: EvidenceContext, container_id: str, log_ref: str | None
) -> None:
    """Fill only details backed by an actual snapshot or a successful log read."""
    refs = [ref for ref, row in context.snapshots.items() if row.id == container_id]
    if not refs:
        return
    status_ref = max(enumerate(refs), key=lambda pair: (context.snapshots[pair[1]].observed_at, pair[0]))[1]
    _include_card(cards, "container_status", status_ref, refs)
    if log_ref:
        _include_card(cards, "log_anomalies", log_ref, refs)


def _include_card(cards: list[WidgetProposal], kind: str, ref: str, resource_refs: list[str]) -> None:
    """Retain model recommendations while filling missing factual cards without duplicates."""
    if len(cards) < 16 and not any(
        card.widget_type == kind and set(card.evidence_ids).intersection(resource_refs) for card in cards
    ):
        cards.append(WidgetProposal.model_validate({"widget_type": kind, "evidence_ids": [ref]}))


def _stack_card(refs: list[str], context: EvidenceContext) -> ComposeStackCard:
    """Require stack evidence before constructing a server-owned stack card."""
    ref = next((ref for ref in refs if ref in context.stacks), None)
    if ref is None:
        raise DockSightError("invalid_evidence", "Stack card requires stack evidence", 502)
    stacks = context.stacks[ref]
    if context.group:
        target = context.group.summary
        stacks = tuple(row for row in stacks if (row.kind, row.name) == (target.kind, target.name))
        if not stacks:
            raise DockSightError("resource_outside_group", "Card is outside the selected group", 502)
    return ComposeStackCard(host=context.evidence[ref].host, stacks=list(stacks), evidence_ids=refs)


def _container_snapshot(refs: list[str], context: EvidenceContext) -> ContainerSnapshot:
    """Resolve card references to one exact container and use its latest snapshot."""
    snapshots = [row for ref, row in context.snapshots.items() if ref in refs]
    if not snapshots or len({(row.host, row.id) for row in snapshots}) != 1:
        raise DockSightError("invalid_evidence", "Card requires evidence for one exact container", 502)
    snapshot = max(enumerate(snapshots), key=lambda item: (item[1].observed_at, item[0]))[1]
    if context.group and snapshot.id not in context.group.summary.container_ids:
        raise DockSightError("resource_outside_group", "Card is outside the selected group", 502)
    return snapshot
