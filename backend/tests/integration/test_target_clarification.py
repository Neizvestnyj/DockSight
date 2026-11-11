import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from docksight.application.ports.models import ModelReply
from docksight.bootstrap import Settings, build_components
from docksight.main import create_app
from tests.fakes import DiscoveryRuntime, FakeRuntime, ScriptedModel


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ({"container_id": "b" * 64}, "container_not_found"),
        ({"container_id": "a" * 12}, "validation_error"),
        ({"container_id": "a" * 64, "group": {"kind": "compose", "name": "vintoria-db"}}, "validation_error"),
    ],
)
def test_selected_container_rejects_missing_short_or_conflicting_scope(target: dict[str, object], code: str) -> None:
    runtime = FakeRuntime()
    model = ScriptedModel([])
    settings = Settings(state_backend="memory", api_token="target-integration-token-24", _env_file=None)
    components = build_components(settings, reader=runtime, writer=runtime, model=model)
    with TestClient(create_app(settings, components)) as api:
        result = api.post(
            "/api/v1/chat/turns",
            headers={"Authorization": "Bearer target-integration-token-24"},
            json={"host": "local", "query": "Could vintoria-db simply be stopped?", **target},
        )
    if code == "container_not_found":
        events = [json.loads(line[6:]) for line in result.text.splitlines() if line.startswith("data: ")]
        assert events[-1]["type"] == "turn.failed" and events[-1]["code"] == code
    else:
        assert result.status_code == 422
    assert not model.requests and not runtime.mutations


def test_container_project_clarification_can_continue_with_the_project() -> None:
    runtime = DiscoveryRuntime()
    runtime.rows = (*runtime.rows[:2], replace(runtime.rows[2], name="other-project"))
    model = ScriptedModel(
        [
            ModelReply("Ready"),
            ModelReply('{"summary":"Observed project","uncertain":true,"evidence_ids":[],"widgets":[]}'),
        ]
    )
    settings = Settings(state_backend="memory", api_token="target-integration-token-24", _env_file=None)
    components = build_components(settings, reader=runtime, writer=runtime, model=model)
    headers = {"Authorization": "Bearer target-integration-token-24"}
    body = {"host": "local", "query": "Could other-project simply be stopped?"}
    with TestClient(create_app(settings, components)) as api:
        first = api.post("/api/v1/chat/turns", headers=headers, json=body)
        events = [json.loads(line[6:]) for line in first.text.splitlines() if line.startswith("data: ")]
        assert events[-1]["type"] == "turn.completed"
        assert any(event["type"] == "clarification.required" for event in events)
        assert not model.requests
        result = api.post(
            "/api/v1/chat/turns",
            headers=headers,
            json={**body, "session_id": events[0]["session_id"], "group": {"kind": "compose", "name": "other-project"}},
        )
    completed = [json.loads(line[6:]) for line in result.text.splitlines() if line.startswith("data: ")]
    assert completed[-1]["type"] == "turn.completed"
    answer = next(event["answer"] for event in completed if event["type"] == "answer.ready")
    assert answer["group"]["summary"]["name"] == "other-project"
    assert answer["group"]["summary"]["total"] == 1
