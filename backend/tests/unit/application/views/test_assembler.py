from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.views.assembler import ViewAssembler
from docksight.application.views.schemas import ActionView, ContainerStatusCard, DiagnosisProposal
from docksight.domain.actions import Operation
from docksight.domain.errors import DockSightError
from tests.fakes import snapshot


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
