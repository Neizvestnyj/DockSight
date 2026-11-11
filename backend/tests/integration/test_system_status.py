from fastapi.testclient import TestClient

from docksight.application.ports.status import ProbeResult
from docksight.bootstrap import Settings, build_components
from docksight.main import create_app
from tests.fakes import FakeRuntime, ScriptedModel


def test_system_status_is_authenticated_scoped_and_never_generates_or_discloses_secrets() -> None:
    class MetadataProbe:
        """Report an unreachable model while leaving Docker usable."""

        async def check(self) -> tuple[ProbeResult, ProbeResult]:
            """Simulate provider reachability and a confirmed missing model."""
            return ProbeResult("available", "ok"), ProbeResult("unavailable", "model_not_found")

    token = "test-token-at-least-24-characters"
    settings = Settings(
        state_backend="memory",
        api_token=token,
        model_base_url="http://private-endpoint",
        model_api_key="private-key",
        _env_file=None,
    )
    runtime, model = FakeRuntime(), ScriptedModel([])
    components = build_components(settings, reader=runtime, writer=runtime, model=model, model_probe=MetadataProbe())
    with TestClient(create_app(settings, components)) as api:
        assert api.get("/api/v1/system/status?host=local").status_code == 401
        headers = {"Authorization": f"Bearer {token}"}
        response = api.get("/api/v1/system/status?host=local", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "ollama"
        assert body["model"] == "qwen3.5:9b"
        assert body["docker"]["state"] == "available"
        assert body["model_check"]["state"] == "unavailable"
        assert body["docker"]["checked_at"].endswith("Z")
        assert "private-" not in response.text
        assert token not in response.text
        assert api.get("/api/v1/system/status?host=unknown", headers=headers).status_code == 404
        assert api.get("/api/v1/system/status?host=http://private-endpoint", headers=headers).status_code == 422
        assert api.get("/api/v1/system/status", headers=headers).json()["docker"]["state"] == "not_checked"
        assert api.get("/health/live").json()["status"] == "ok"
        assert api.get("/health/ready").json() == {"status": "ready"}
    assert model.requests == []
    assert runtime.mutations == []
