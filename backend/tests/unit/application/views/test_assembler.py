from dataclasses import replace
from datetime import timedelta

import pytest

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.views.assembler import ViewAssembler
from docksight.application.views.schemas import ContainerStatusCard, DiagnosisProposal
from docksight.domain.errors import DockSightError
from tests.fakes import snapshot


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
