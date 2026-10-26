import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

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
    """Verify configured model produces an evidence linked card."""
    settings = Settings()
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
        events = [
            event
            async for event in components.diagnostics.stream(
                "operator",
                "local",
                case.get(
                    "query",
                    "Inspect worker and include its container_status card. Explain only what the evidence supports.",
                ),
            )
        ]
        assert events[-1]["type"] == "turn.completed", events[-1]
        answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
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
