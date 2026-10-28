import json

from fastapi.testclient import TestClient

from docksight.application.ports.models import ModelReply
from docksight.bootstrap import Settings, build_components
from docksight.main import create_app
from tests.fakes import FakeRuntime, ScriptedModel


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
