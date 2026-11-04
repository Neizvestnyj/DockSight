import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from docksight.application.ports.models import ModelReply, ToolCall
from docksight.bootstrap import Settings, build_components
from docksight.main import create_app
from tests.fakes import FakeRuntime, ScriptedModel

TOKEN = "test-token-at-least-24-characters"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
ALICE = {"Authorization": "Bearer alice-token-at-least-24-characters"}
BOB = {"Authorization": "Bearer bob-token-at-least-24-characters"}


def client(suggested: bool = False, api_tokens: dict[str, str] | None = None) -> TestClient:
    """Create an authenticated in-process client with deterministic runtime and model ports."""
    settings = Settings(
        api_token=TOKEN,
        api_tokens=api_tokens or {},
        cors_origins=("http://localhost:5173",),
        _env_file=None,
    )
    runtime = FakeRuntime()
    model = ScriptedModel(
        [
            ModelReply("", (ToolCall("c1", "inspect_container", {"container_id": "worker"}),)),
            ModelReply("Ready"),
            ModelReply(
                json.dumps(
                    {
                        "summary": "Worker exited",
                        "uncertain": True,
                        "evidence_ids": ["e1"],
                        "widgets": [
                            {
                                "widget_type": "container_status",
                                "evidence_ids": ["e1"],
                                "action": "restart" if suggested else None,
                                "action_reason": f"Review {TOKEN}" if suggested else None,
                            }
                        ],
                    }
                )
            ),
        ]
    )
    components = build_components(settings, reader=runtime, writer=runtime, model=model)
    return TestClient(create_app(settings, components))


def test_http_authentication_hosts_and_unknown_host() -> None:
    with client() as api:
        assert api.get("/api/v1/hosts").status_code == 401
        response = api.get("/api/v1/hosts", headers=HEADERS)
        assert response.json() == [{"id": "local", "name": "Local"}]
        assert api.get("/api/v1/hosts/unknown/containers", headers=HEADERS).status_code == 404
        assert api.get("/api/v1/widgets/schema", headers=HEADERS).json()["schema_version"] == 1


def test_streamed_diagnosis_contains_validated_cards_and_terminal_event() -> None:
    with client() as api:
        response = api.post("/api/v1/chat/turns", headers=HEADERS, json={"host": "local", "query": "Inspect worker"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
        assert answer["widgets"][0]["snapshot"]["id"] == "a" * 64
        action = answer["widgets"][0]["actions"][0]
        assert action["confirmation_required"] is True
        assert events[-1]["type"] == "turn.completed"
        assert all(event["request_id"] == response.headers["x-request-id"] for event in events)


def test_streamed_trace_contains_public_configuration_and_sanitized_proposal() -> None:
    with client() as api:
        response = api.post("/api/v1/chat/turns", headers=HEADERS, json={"host": "local", "query": "Inspect worker"})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        trace = next(event for event in events if event["type"] == "trace.started")
        assert (trace["provider"], trace["model"]) == ("ollama", "qwen3.5:9b")
        steps = [event["step"] for event in events if event["type"] == "trace.step"]
        assert steps[-1]["state"] == "succeeded"
        assert steps[-1]["operation"] == "validate_diagnosis"
        assert any(step["response"] and '"summary": "Worker exited"' in step["response"] for step in steps)
        assert TOKEN not in response.text


def test_action_endpoint_requires_confirmation_and_deduplicates_execution() -> None:
    with client() as api:
        prepared = api.post(
            "/api/v1/actions",
            headers=HEADERS,
            json={"host": "local", "container_id": "a" * 64, "operation": "restart"},
        )
        assert prepared.status_code == 201
        action_id = prepared.json()["id"]
        path = f"/api/v1/actions/{action_id}/execute"
        assert api.post(path, headers=HEADERS, json={"confirmed": True}).status_code == 422
        headers = {**HEADERS, "Idempotency-Key": "request-1"}
        assert api.post(path, headers=headers, json={"confirmed": False}).status_code == 409
        result = api.post(path, headers=headers, json={"confirmed": True})
        assert result.json()["state"] == "succeeded"
        assert api.post(path, headers=headers, json={"confirmed": True}).json() == result.json()


def test_named_tokens_isolate_actions_and_sessions_between_actors() -> None:
    tokens = {"alice": ALICE["Authorization"][7:], "bob": BOB["Authorization"][7:]}
    with client(api_tokens=tokens) as api:
        prepared = api.post(
            "/api/v1/actions",
            headers=ALICE,
            json={"host": "local", "container_id": "a" * 64, "operation": "restart"},
        ).json()
        path = f"/api/v1/actions/{prepared['id']}"
        for headers in (BOB, HEADERS):
            assert api.get(path, headers=headers).json()["code"] == "action_not_found"
            execute_headers = {**headers, "Idempotency-Key": "k-1"}
            denied = api.post(f"{path}/execute", headers=execute_headers, json={"confirmed": True})
            assert denied.status_code == 404
        assert api.get(path, headers=ALICE).json()["state"] == "prepared"

        turn = api.post("/api/v1/chat/turns", headers=ALICE, json={"host": "local", "query": "Inspect worker"})
        events = [json.loads(line[6:]) for line in turn.text.splitlines() if line.startswith("data: ")]
        session_id = events[0]["session_id"]
        follow_up = api.post(
            "/api/v1/chat/turns",
            headers=BOB,
            json={"host": "local", "query": "And now?", "session_id": session_id},
        )
        failed = [json.loads(line[6:]) for line in follow_up.text.splitlines() if line.startswith("data: ")][-1]
        assert (failed["type"], failed["code"]) == ("turn.failed", "session_not_found")
        assert tokens["alice"] not in turn.text + follow_up.text


def test_recommended_action_uses_server_id_and_redacts_its_model_reason() -> None:
    with client(suggested=True) as api:
        response = api.post("/api/v1/chat/turns", headers=HEADERS, json={"host": "local", "query": "Inspect worker"})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        card = next(event["answer"]["widgets"][0] for event in events if event["type"] == "answer.ready")
        assert card["recommendation"] == {"action_id": card["actions"][0]["id"], "reason": "Review [REDACTED]"}
        assert TOKEN not in response.text


def test_cors_preflight_does_not_require_a_token_and_foreign_origin_is_rejected() -> None:
    with client() as api:
        response = api.options(
            "/api/v1/chat/turns",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert api.get("/api/v1/hosts", headers={**HEADERS, "Origin": "http://foreign.example"}).status_code == 403


def test_invalid_and_oversized_requests_do_not_echo_sensitive_input() -> None:
    with client() as api:
        response = api.post(
            "/api/v1/chat/turns",
            headers=HEADERS,
            json={"host": "local", "query": "valid", "api_key": "private-sentinel"},
        )
        assert response.status_code == 422
        assert "private-sentinel" not in response.text
        response = api.post("/api/v1/chat/turns", headers=HEADERS, content=b"x" * 20000)
        assert response.status_code == 413
        assert response.json()["code"] == "request_too_large"
        assert response.json()["request_id"] == response.headers["x-request-id"]


def test_chunked_requests_are_limited_without_content_length() -> None:
    with client() as api:
        response = api.post(
            "/api/v1/chat/turns",
            headers={**HEADERS, "Content-Type": "application/json"},
            content=iter([b"x" * 10000, b"y" * 10000]),
        )
        assert response.status_code == 413
        assert response.json()["code"] == "request_too_large"
        assert response.json()["message"] == "Request body exceeds 16 KiB"
        assert response.json()["request_id"] == response.headers["x-request-id"]


def test_application_version_comes_from_installed_distribution() -> None:
    with patch("importlib.metadata.version", return_value="9.8.7") as lookup, client() as api:
        assert api.get("/health/live").json()["version"] == "9.8.7"
        assert api.get("/openapi.json").json()["info"]["version"] == "9.8.7"
        lookup.assert_called_with("docksight")


def test_openapi_describes_authentication_and_sse() -> None:
    with client() as api:
        document = api.get("/openapi.json").json()
        chat = document["paths"]["/api/v1/chat/turns"]["post"]
        assert "text/event-stream" in chat["responses"]["200"]["content"]
        assert chat["security"] == [{"HTTPBearer": []}, {"BrowserCookie": []}]
