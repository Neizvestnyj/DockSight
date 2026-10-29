import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.integration.live_e2e.cases import Case, Language
from tests.integration.live_e2e.checks import check_answer
from tests.integration.live_e2e.lab import ComposeLab
from tests.integration.live_e2e.reports import record_run, report_path

pytestmark = [pytest.mark.live, pytest.mark.docker]


def test_live_diagnosis(
    api: httpx.Client, lab: ComposeLab, case: Case, language: Language, model_name: str, artifacts: Path
) -> None:
    """Run the real HTTP/SSE, application, Docker, and local-model path without scripted model replies."""
    events: list[dict[str, Any]] = []
    container_id = next(iter(lab.containers.values())).id
    payload: dict[str, Any] = {"host": "e2e", "query": case.query(lab.project, container_id, language)}
    if case.explicit:
        payload["group"] = {"kind": "compose", "name": lab.project}
    started = datetime.now(UTC).isoformat()
    try:
        with api.stream("POST", "/api/v1/chat/turns", json=payload) as response:
            response.raise_for_status()
            assert response.headers["content-type"].startswith("text/event-stream")
            for line in response.iter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    events.append(event)
                    if event["type"] in {"tool.started", "turn.failed", "turn.completed"}:
                        print(f"[{model_name}/{case.name}] {event['type']} {event.get('tool', '')}", flush=True)
        check_answer(events, lab, case, language)
    finally:
        record_run(report_path(artifacts, model_name, case, language), lab, model_name, started, payload, events)
