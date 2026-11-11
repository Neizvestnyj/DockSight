from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from docksight.bootstrap import Settings, build_components
from docksight.main import create_app
from tests.fakes import FakeRuntime, ScriptedModel


def test_provider_catalog_is_private_safe_and_keeps_default_without_metadata() -> None:
    """Injected adapters retain the default path and never allocate provider clients implicitly."""
    token = "test-token-at-least-24-characters"
    settings = Settings(
        state_backend="memory",
        api_token=token,
        model_base_url="http://private-endpoint",
        model_api_key="private-key",
        _env_file=None,
    )
    runtime, model = FakeRuntime(), ScriptedModel([])
    components = build_components(settings, reader=runtime, writer=runtime, model=model)
    with TestClient(create_app(settings, components)) as api:
        assert api.get("/api/v1/model-providers").status_code == 401
        headers = {"Authorization": f"Bearer {token}"}
        response = api.get("/api/v1/model-providers", headers=headers)
        assert response.status_code == 200
        assert response.json()["default"] == {"provider": "ollama", "model": "qwen3.5:9b"}
        assert len(response.json()["providers"]) == 5
        assert "private-" not in response.text
        assert token not in response.text
        catalog = api.get("/api/v1/model-providers/ollama/models", headers=headers)
        assert catalog.status_code == 200
        assert catalog.json()["models"] == [{"id": "qwen3.5:9b"}]
        assert catalog.json()["state"] == "unavailable"
        assert catalog.json()["code"] == "unsupported"
        assert api.get("/api/v1/model-providers/unknown/models", headers=headers).status_code == 422
        selected = api.get("/api/v1/system/status?provider=ollama&model=qwen3.5:9b", headers=headers)
        assert selected.status_code == 200
        assert selected.json()["provider"] == "ollama"
        assert selected.json()["model"] == "qwen3.5:9b"
        assert api.get("/api/v1/system/status?provider=ollama", headers=headers).status_code == 422
        assert api.get("/api/v1/system/status?provider=unknown&model=x", headers=headers).status_code == 422
        assert api.get("/api/v1/system/status?provider=ollama&model=unlisted", headers=headers).status_code == 422
    assert model.requests == []
    assert runtime.mutations == []


def test_turn_selection_is_validated_before_streaming() -> None:
    """Unknown identities and private connection fields cannot reach model generation."""
    token = "test-token-at-least-24-characters"
    settings = Settings(state_backend="memory", api_token=token, _env_file=None)
    runtime, model = FakeRuntime(), ScriptedModel([])
    components = build_components(settings, reader=runtime, writer=runtime, model=model)
    selections = [
        {"provider": "unknown", "model": "x"},
        {"provider": "ollama", "model": "unlisted"},
        {"provider": "ollama", "model": "x", "base_url": "http://private"},
        {"provider": "ollama", "model": "x" * 257},
    ]
    with TestClient(create_app(settings, components)) as api:
        for selection in selections:
            response = api.post(
                "/api/v1/chat/turns",
                headers={"Authorization": f"Bearer {token}"},
                json={"host": "local", "query": "Inspect worker", "model_selection": selection},
            )
            assert response.status_code == 422
            assert "text/event-stream" not in response.headers["content-type"]
    assert model.requests == []


def test_unknown_status_host_is_rejected_before_selected_provider_work() -> None:
    """A caller cannot trigger provider metadata checks through an unconfigured Docker scope."""
    token = "test-token-at-least-24-characters"
    settings = Settings(state_backend="memory", api_token=token, _env_file=None)
    runtime = FakeRuntime()
    components = build_components(settings, reader=runtime, writer=runtime, model=ScriptedModel([]))
    assert components.models is not None
    selected = AsyncMock(side_effect=AssertionError("Provider work must follow host validation"))
    components.models.select = selected
    with TestClient(create_app(settings, components)) as api:
        response = api.get(
            "/api/v1/system/status?host=unknown&provider=ollama&model=unlisted",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
        assert response.json()["code"] == "host_not_found"
    selected.assert_not_called()
