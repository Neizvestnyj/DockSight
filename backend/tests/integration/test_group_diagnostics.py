import json
from dataclasses import replace

from fastapi.testclient import TestClient

from docksight.application.ports.models import ModelReply, ToolCall
from docksight.bootstrap import Settings, build_components
from docksight.main import create_app
from tests.fakes import DiscoveryRuntime, FakeRuntime, ScriptedModel


def test_unscoped_question_collects_no_logs_until_the_operator_selects_a_project() -> None:
    runtime = DiscoveryRuntime()
    model = ScriptedModel(
        [
            ModelReply("Ready"),
            ModelReply(
                json.dumps({"summary": "Two members failed", "uncertain": True, "evidence_ids": [], "widgets": []})
            ),
        ]
    )
    settings = Settings(api_token="unscoped-integration-token-24", _env_file=None)
    components = build_components(settings, reader=runtime, writer=runtime, model=model)
    headers = {"Authorization": "Bearer unscoped-integration-token-24"}
    body = {"host": "local", "query": "Что случилось?"}
    with TestClient(create_app(settings, components)) as api:
        first = api.post("/api/v1/chat/turns", headers=headers, json=body)
        events = [json.loads(line[6:]) for line in first.text.splitlines() if line.startswith("data: ")]
        assert events[-1]["type"] == "turn.completed"
        selection = next(event["selection"] for event in events if event["type"] == "clarification.required")
        assert {row["name"] for row in selection["candidates"]} == {"other-project", "vintoria-infra"}
        assert not any(event["type"] == "answer.ready" for event in events)
        assert not runtime.reads
        assert not model.requests
        second = api.post(
            "/api/v1/chat/turns", headers=headers, json={**body, "group": {"kind": "compose", "name": "vintoria-infra"}}
        )
    completed = [json.loads(line[6:]) for line in second.text.splitlines() if line.startswith("data: ")]
    assert completed[-1]["type"] == "turn.completed"
    answer = next(event["answer"] for event in completed if event["type"] == "answer.ready")
    assert answer["group"]["summary"]["name"] == "vintoria-infra"
    assert len(answer["widgets"]) == 4
    assert set(runtime.reads) == {"1" * 64, "2" * 64}


def test_group_follow_up_keeps_history_and_reads_an_explicit_container_with_a_colliding_project_name() -> None:
    runtime = DiscoveryRuntime()
    runtime.rows = (*runtime.rows[:2], replace(runtime.rows[2], name="other-project"))
    first_query = "What happened to vintoria-infra?"
    summary = "Two members exited while connecting to their dependency."
    model = ScriptedModel(
        [
            ModelReply("Ready"),
            ModelReply(json.dumps({"summary": summary, "uncertain": True, "evidence_ids": ["e1"], "widgets": []})),
            ModelReply("Ready"),
            ModelReply(
                json.dumps(
                    {
                        "summary": "The dependency container exited.",
                        "uncertain": True,
                        "evidence_ids": ["e1", "e2"],
                        "widgets": [
                            {"widget_type": "container_status", "evidence_ids": ["e1"]},
                            {"widget_type": "log_anomalies", "evidence_ids": ["e2"]},
                        ],
                    }
                )
            ),
        ]
    )
    settings = Settings(api_token="followup-integration-token-24", _env_file=None)
    components = build_components(settings, reader=runtime, writer=runtime, model=model)
    headers = {"Authorization": "Bearer followup-integration-token-24"}
    with TestClient(create_app(settings, components)) as api:
        first = api.post("/api/v1/chat/turns", headers=headers, json={"host": "local", "query": first_query})
        events = [json.loads(line[6:]) for line in first.text.splitlines() if line.startswith("data: ")]
        original = next(event["answer"] for event in events if event["type"] == "answer.ready")
        session_id = events[0]["session_id"]
        second = api.post(
            "/api/v1/chat/turns",
            headers=headers,
            json={
                "host": "local",
                "session_id": session_id,
                "query": "Maybe the dependency is stopped? Check container other-project.",
            },
        )
    followup = [json.loads(line[6:]) for line in second.text.splitlines() if line.startswith("data: ")]
    assert followup[0]["session_id"] == session_id
    assert followup[-1]["type"] == "turn.completed"
    answer = next(event["answer"] for event in followup if event["type"] == "answer.ready")
    assert answer["group"] is None
    assert answer["widgets"][0]["snapshot"]["id"] == "3" * 64
    assert answer["widgets"][1]["container_id"] == "3" * 64
    assert [(row.role, row.content) for row in model.requests[2][0] if row.role != "system"][:2] == [
        ("user", first_query),
        ("assistant", summary),
    ]
    assert len(original["widgets"]) == 4
    assert original["group"]["summary"]["name"] == "vintoria-infra"
    assert runtime.reads == ["1" * 64, "2" * 64, "3" * 64]


def test_authorized_clarification_completes_without_answer_and_continues_with_exact_group() -> None:
    settings = Settings(api_token="clarification-integration-token-24", _env_file=None)
    runtime = DiscoveryRuntime()
    model = ScriptedModel(
        [
            ModelReply(
                "",
                (
                    ToolCall(
                        "choose",
                        "request_group_selection",
                        {
                            "candidates": [
                                {"kind": "compose", "name": "vintoria-infra"},
                                {"kind": "compose", "name": "other-project"},
                            ]
                        },
                    ),
                ),
            ),
            ModelReply("Ready"),
            ModelReply(
                json.dumps({"summary": "Two members failed", "uncertain": True, "widgets": [], "evidence_ids": ["e1"]})
            ),
        ]
    )
    components = build_components(settings, reader=runtime, writer=runtime, model=model)
    body = {"host": "local", "query": "Что не так \u0441 винтория инфра?"}
    headers = {"Authorization": "Bearer clarification-integration-token-24"}
    with TestClient(create_app(settings, components)) as api:
        assert api.post("/api/v1/chat/turns", json=body).status_code == 401
        response = api.post("/api/v1/chat/turns", headers=headers, json=body)
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert response.status_code == 200
        assert events[-1]["type"] == "turn.completed"
        choices = [event for event in events if event["type"] == "clarification.required"]
        assert len(choices) == 1
        assert all(event["request_id"] == response.headers["x-request-id"] for event in events)
        assert all(event["schema_version"] == 1 for event in events)
        assert not runtime.reads
        assert not any(event["type"] == "answer.ready" for event in events)
        followup = api.post(
            "/api/v1/chat/turns",
            headers=headers,
            json={
                **body,
                "session_id": events[0]["session_id"],
                "group": {"kind": "compose", "name": "vintoria-infra"},
            },
        )
    completed = [json.loads(line[6:]) for line in followup.text.splitlines() if line.startswith("data: ")]
    assert completed[-1]["type"] == "turn.completed"
    answer = next(event["answer"] for event in completed if event["type"] == "answer.ready")
    assert answer["group"]["summary"]["name"] == "vintoria-infra"
    assert len(answer["widgets"]) == 4
    assert set(runtime.reads) == {"1" * 64, "2" * 64}


def test_explicit_group_contract_collects_evidence_and_redacts_each_cause_field() -> None:
    token = "group-integration-token-24-characters"
    settings = Settings(api_token=token, _env_file=None)
    runtime = FakeRuntime()
    model = ScriptedModel(
        [
            ModelReply("Ready"),
            ModelReply(
                json.dumps(
                    {
                        "summary": "Startup failed",
                        "uncertain": True,
                        "widgets": [],
                        "evidence_ids": ["e1"],
                        "cause": {
                            "immediate": f"Connection failed {token}",
                            "underlying": f"Unknown {token}",
                            "unknowns": [f"Database availability {token}"],
                            "evidence_ids": ["e3"],
                        },
                    }
                )
            ),
        ]
    )
    components = build_components(settings, reader=runtime, writer=runtime, model=model)
    with TestClient(create_app(settings, components)) as api:
        headers = {"Authorization": f"Bearer {token}"}
        invalid = api.post(
            "/api/v1/chat/turns",
            headers=headers,
            json={"host": "local", "query": "Check", "group": {"kind": "compose", "name": "demo", "host": "other"}},
        )
        assert invalid.status_code == 422
        assert not model.requests
        response = api.post(
            "/api/v1/chat/turns",
            headers=headers,
            json={"host": "local", "query": "Check", "group": {"kind": "compose", "name": "demo"}},
        )
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "turn.completed"
    answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
    assert answer["group"]["summary"]["kind"] == "compose"
    assert answer["group"]["logs"][0]["state"] == "collected"
    assert answer["cause"]["immediate"] == "Connection failed [REDACTED]"
    assert answer["cause"]["underlying"] == "Unknown [REDACTED]"
    assert answer["cause"]["unknowns"] == ["Database availability [REDACTED]"]
    assert token not in response.text
    assert not runtime.mutations
