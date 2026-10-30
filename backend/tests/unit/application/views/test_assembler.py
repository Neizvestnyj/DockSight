from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.views.assembler import ViewAssembler
from docksight.application.views.schemas import (
    ActionView,
    ContainerStatusCard,
    DiagnosisProposal,
    GroupInspection,
    GroupLogResult,
    LogAnomalyCard,
)
from docksight.domain.actions import Operation
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import LogBatch, LogEntry, StackSummary
from tests.fakes import snapshot


async def test_selected_container_keeps_collected_facts_when_the_model_omits_all_cards() -> None:
    item = snapshot()
    context = EvidenceContext(container_id=item.id)
    context.record("container", "local", {}, item)
    logs = LogBatch((LogEntry("Connection refused"),))
    context.record("logs", "local", {}, item, logs)
    answer = await ViewAssembler().build(
        DiagnosisProposal(summary="The dependency is unavailable", uncertain=True, evidence_ids=[], widgets=[]),
        context,
        "alice",
    )
    assert len(answer.widgets) == 2
    assert isinstance(answer.widgets[0], ContainerStatusCard)
    assert answer.widgets[0].snapshot == item
    assert isinstance(answer.widgets[1], LogAnomalyCard)
    assert answer.widgets[1].logs == logs
    assert all(row.container_id == item.id for row in answer.evidence)


async def test_identical_proposals_do_not_duplicate_cards_or_action_preparation() -> None:
    context = EvidenceContext()
    context.record("container", "local", {}, snapshot())
    proposal = DiagnosisProposal.model_validate(
        {
            "summary": "Observed",
            "uncertain": True,
            "evidence_ids": ["e1"],
            "widgets": [{"widget_type": "container_status", "evidence_ids": ["e1"]}] * 2,
        }
    )
    prepared: list[Operation] = []

    async def prepare(actor: str, host: str, container_id: str, operation: Operation) -> ActionView:
        """Track preparation once for each permitted operation on the observed target."""
        prepared.append(operation)
        return ActionView(
            id=str(uuid4()),
            host=host,
            container_id=container_id,
            operation=operation,
            expires_at=snapshot().observed_at + timedelta(minutes=5),
            state="prepared",
            message="Confirm",
        )

    answer = await ViewAssembler(prepare).build(proposal, context, "alice")
    assert len(answer.widgets) == 1
    assert prepared == ["restart"]


@pytest.mark.parametrize(
    ("state", "suggested", "permitted", "expected"),
    [
        ("running", None, {"restart", "stop"}, None),
        ("running", "restart", {"restart", "stop"}, "restart"),
        ("running", "stop", {"restart", "stop"}, "stop"),
        ("exited", "stop", {"restart"}, None),
        ("paused", "restart", set(), None),
    ],
)
async def test_recommendation_links_only_the_explicit_model_operation_to_a_prepared_action(
    state: str,
    suggested: str | None,
    permitted: set[str],
    expected: str | None,
) -> None:
    item = replace(snapshot(), state=state)
    context = EvidenceContext()
    context.record("container", "local", {}, item)

    async def prepare(actor: str, host: str, container_id: str, operation: Operation) -> ActionView:
        """Issue opaque IDs using the real exact resource passed by the assembler."""
        assert (actor, host, container_id) == ("alice", "local", item.id)
        return ActionView(
            id=str(uuid4()),
            host=host,
            container_id=container_id,
            operation=operation,
            expires_at=item.observed_at + timedelta(minutes=5),
            state="prepared",
            message="Confirm",
        )

    proposal = DiagnosisProposal.model_validate(
        {
            "summary": "Observed",
            "uncertain": False,
            "evidence_ids": ["e1"],
            "widgets": [
                {
                    "widget_type": "container_status",
                    "evidence_ids": ["e1"],
                    "action": suggested,
                    "action_reason": "Operator requested maintenance." if suggested else None,
                }
            ],
        }
    )
    answer = await ViewAssembler(prepare).build(proposal, context, "alice")
    card = answer.widgets[0]
    assert isinstance(card, ContainerStatusCard)
    assert {action.operation for action in card.actions} == permitted
    if expected is None:
        assert card.recommendation is None
    else:
        assert card.recommendation is not None
        action = next(action for action in card.actions if action.id == card.recommendation.action_id)
        assert action.operation == expected
        assert card.recommendation.reason == "Operator requested maintenance."


@pytest.mark.parametrize("references", [["e2", "e1"], ["e1", "e2"]])
@pytest.mark.parametrize("tied", [False, True])
async def test_container_card_uses_latest_server_snapshot(references: list[str], tied: bool) -> None:
    context = EvidenceContext()
    old = snapshot()
    newest = replace(old, state="running", observed_at=old.observed_at + timedelta(seconds=0 if tied else 1))
    context.record("container", "local", {}, old)
    context.record("container", "local", {}, newest)
    proposal = DiagnosisProposal.model_validate(
        {
            "summary": "Observed",
            "uncertain": False,
            "evidence_ids": references,
            "widgets": [{"widget_type": "container_status", "evidence_ids": references}],
        }
    )
    answer = await ViewAssembler().build(proposal, context, "alice")
    assert isinstance(answer.widgets[0], ContainerStatusCard)
    assert answer.widgets[0].snapshot.state == "running"


async def test_container_card_rejects_mixed_hosts() -> None:
    context = EvidenceContext()
    item = snapshot()
    context.record("container", "local", {}, item)
    context.record("container", "other", {}, replace(item, host="other"))
    proposal = DiagnosisProposal.model_validate(
        {
            "summary": "Observed",
            "uncertain": False,
            "evidence_ids": ["e1", "e2"],
            "widgets": [{"widget_type": "container_status", "evidence_ids": ["e1", "e2"]}],
        }
    )
    with pytest.raises(DockSightError, match="one exact container"):
        await ViewAssembler().build(proposal, context, "alice")


async def test_cause_references_must_resolve_even_when_the_summary_has_no_references() -> None:
    proposal = DiagnosisProposal.model_validate(
        {
            "summary": "Failure",
            "uncertain": True,
            "evidence_ids": [],
            "widgets": [],
            "cause": {
                "immediate": "Database connection failed",
                "underlying": None,
                "unknowns": ["Database availability"],
                "evidence_ids": ["invented"],
            },
        }
    )
    with pytest.raises(DockSightError, match="unknown evidence"):
        await ViewAssembler().build(proposal, EvidenceContext(), "alice")


async def test_added_group_status_uses_the_latest_observation_and_its_action_policy() -> None:
    old = snapshot()
    latest = replace(old, state="running", observed_at=old.observed_at + timedelta(seconds=1))
    summary = StackSummary("infra", "compose", 1, 0, (old.id,))
    context = EvidenceContext()
    context.record("stack", "local", {}, stacks=(summary,))
    context.record("container", "local", {}, old)
    context.record("container", "local", {}, latest)
    context.group = GroupInspection(
        summary=summary,
        evidence_id="e1",
        logs=[GroupLogResult(container_id=old.id, name=old.name, state="failed", code="runtime_unavailable")],
    )

    async def prepare(actor: str, host: str, container_id: str, operation: Operation) -> ActionView:
        """Expose the operation selected by the observed state without executing a mutation."""
        return ActionView(
            id=str(uuid4()),
            host=host,
            container_id=container_id,
            operation=operation,
            expires_at=latest.observed_at + timedelta(minutes=5),
            state="prepared",
            message="Confirm",
        )

    proposal = DiagnosisProposal(summary="Observed", uncertain=True, evidence_ids=["e1"], widgets=[])
    answer = await ViewAssembler(prepare).build(proposal, context, "alice")
    card = answer.widgets[0]
    assert isinstance(card, ContainerStatusCard)
    assert card.snapshot == latest
    assert card.evidence_ids == ["e3"]
    assert {action.operation for action in card.actions} == {"restart", "stop"}
