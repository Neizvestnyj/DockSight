import json
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from docksight.application.investigations.contracts import QuestionTurn, StartTurn
from docksight.bootstrap import Settings, build_components
from docksight.domain.runtime import LogBatch, LogEntry
from tests.fakes import FakeRuntime

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("DOCKSIGHT_TEST_LIVE_MODEL") != "1",
        reason="Set DOCKSIGHT_TEST_LIVE_MODEL=1",
    ),
]


@pytest.mark.parametrize(
    "case",
    json.loads((Path(__file__).parents[1] / "fixtures/diagnostics.json").read_text()),
    ids=lambda case: case["name"],
)
async def test_configured_model_produces_an_evidence_linked_card(case: dict) -> None:
    settings = Settings(
        state_backend="memory",
    )
    runtime = FakeRuntime()
    runtime.item = replace(
        runtime.item,
        state=case["state"],
        exit_code=case["exit_code"],
        oom_killed=case["oom_killed"],
        restart_count=case["restart_count"],
    )
    runtime.log_batch = LogBatch((LogEntry(case["log"]),) if case["log"] else (), case["truncated"])
    components = build_components(settings, reader=runtime, writer=runtime)
    try:
        await components.start()
        identity = str(uuid4())
        await components.investigations.create("operator", identity, "local")
        accepted = await components.runner.submit(
            "operator",
            StartTurn(
                QuestionTurn(
                    investigation_id=identity,
                    submission_id=str(uuid4()),
                    expected_revision=0,
                    query=case.get(
                        "query",
                        "Inspect worker and include its container_status card. "
                        "Explain only what the evidence supports.",
                    ),
                )
            ),
            "live-model-test",
        )
        snapshots = [saved async for saved in components.runner.observe("operator", accepted.snapshot.id)]
        final = snapshots[-1]
        assert final.state == "completed", final.error
        assert final.answer is not None
        answer = final.answer.model_dump(mode="json")
        assert answer["evidence"]
        assert any(card["widget_type"] == "container_status" for card in answer["widgets"])
        card = next(card for card in answer["widgets"] if card["widget_type"] == "container_status")
        assert card["snapshot"]["state"] == case["state"]
        assert card["snapshot"]["oom_killed"] is case["oom_killed"]
        assert card["snapshot"]["exit_code"] == case["exit_code"]
        if case.get("requires_uncertainty"):
            assert answer["uncertain"] is True
        kinds = {card["widget_type"] for card in answer["widgets"]}
        assert set(case.get("required_widgets", ["container_status"])) <= kinds
    finally:
        await components.close()
