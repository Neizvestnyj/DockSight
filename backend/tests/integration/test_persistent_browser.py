import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from tests.integration.persistence.process import PersistentServer


def test_http_child_recovers_saved_answer_and_cookie_without_generation(tmp_path: Path) -> None:
    with PersistentServer(tmp_path) as server, httpx.Client(base_url=server.origin) as browser:
        assert server.pid != os.getpid()
        login = browser.post(
            "/api/v1/auth/login",
            headers={"Authorization": f"Bearer {server.token}", "Origin": server.origin},
            json={},
        )
        assert login.status_code == 200
        assert "HttpOnly" in login.headers["set-cookie"]
        browser.headers.update({"Origin": server.origin, "X-CSRF-Token": login.json()["csrf_token"]})
        identity = str(uuid4())
        assert browser.post("/api/v1/investigations", json={"id": identity, "host": "local"}).status_code == 201
        accepted = browser.post(
            f"/api/v1/investigations/{identity}/turns",
            json={"kind": "question", "submission_id": str(uuid4()), "expected_revision": 0, "query": "Inspect worker"},
        )
        assert accepted.status_code == 202
        turn_id = accepted.json()["snapshot"]["id"]
        saved = server.wait_turn(browser, turn_id)
        assert saved["state"] == "completed"
        counts = server.events()
        assert sum(row["event"] == "model.final" for row in counts) == 1
        previous_pid = server.pid
        server.restart()
        assert server.pid != previous_pid
        assert browser.get("/api/v1/auth/session").status_code == 200
        assert browser.get(f"/api/v1/turns/{turn_id}").json() == saved
        assert server.events() == counts


def accept(api: httpx.Client) -> tuple[str, dict[str, object]]:
    """Create one owned chat and explicitly submit one question through real HTTP."""
    identity = str(uuid4())
    assert api.post("/api/v1/investigations", json={"id": identity, "host": "local"}).status_code == 201
    body = {"kind": "question", "submission_id": str(uuid4()), "expected_revision": 0, "query": "Inspect worker"}
    result = api.post(f"/api/v1/investigations/{identity}/turns", json=body)
    assert result.status_code == 202
    return result.json()["snapshot"]["id"], body


def test_http_process_death_interrupts_one_turn_and_receipt_never_regenerates(tmp_path: Path) -> None:
    (tmp_path / "model.block").touch()
    with (
        PersistentServer(tmp_path) as server,
        httpx.Client(base_url=server.origin, headers={"Authorization": f"Bearer {server.token}"}) as api,
    ):
        turn_id, body = accept(api)
        server.wait_file("model.entered")
        before = server.events()
        identity = api.get(f"/api/v1/turns/{turn_id}").json()["investigation_id"]
        for _ in range(2):
            server.restart()
            saved = api.get(f"/api/v1/turns/{turn_id}").json()
            assert saved["state"] == "interrupted"
            assert api.get(f"/api/v1/investigations/{identity}").json()["active_turn_id"] is None
            replay = api.post(f"/api/v1/investigations/{identity}/turns", json=body)
            assert replay.status_code == 202 and not replay.json()["created"]
            assert replay.json()["snapshot"] == saved
            assert server.events() == before


@pytest.mark.parametrize("origin", ["", "http://127.0.0.1:1"])
def test_http_public_origin_misconfiguration_rejects_login(tmp_path: Path, origin: str) -> None:
    with PersistentServer(tmp_path, origin=origin) as server, httpx.Client(base_url=server.origin) as browser:
        result = browser.post(
            "/api/v1/auth/login",
            headers={"Authorization": f"Bearer {server.token}", "Origin": "http://127.0.0.1:4173"},
            json={},
        )
        assert result.status_code == 403
        assert not browser.cookies


def test_http_claimed_action_survives_process_death_with_retained_key_and_block(tmp_path: Path) -> None:
    (tmp_path / "mutation.block").touch()
    with (
        PersistentServer(tmp_path) as server,
        httpx.Client(base_url=server.origin, headers={"Authorization": f"Bearer {server.token}"}, timeout=20) as api,
    ):
        prepared = api.post("/api/v1/actions", json={"host": "local", "container_id": "a" * 64, "operation": "restart"})
        assert prepared.status_code == 201
        action_id = prepared.json()["id"]
        path = f"/api/v1/actions/{action_id}"
        with ThreadPoolExecutor(max_workers=1) as pool:
            sent = pool.submit(
                api.post, path + "/execute", headers={"Idempotency-Key": "one-key"}, json={"confirmed": True}
            )
            server.wait_file("mutation.entered")
            assert api.get(path).json()["state"] == "running"
            server.restart()
            with pytest.raises(httpx.HTTPError):
                sent.result(timeout=10)
        for _ in range(2):
            assert api.get(path).json()["state"] == "indeterminate"
            replay = api.post(path + "/execute", headers={"Idempotency-Key": "one-key"}, json={"confirmed": True})
            assert replay.status_code == 200 and replay.json()["state"] == "indeterminate"
            candidate = api.post(
                "/api/v1/actions", json={"host": "local", "container_id": "a" * 64, "operation": "restart"}
            ).json()
            denied = api.post(
                f"/api/v1/actions/{candidate['id']}/execute",
                headers={"Idempotency-Key": "another-key"},
                json={"confirmed": True},
            )
            assert denied.status_code == 409 and denied.json()["code"] == "target_indeterminate"
            server.restart()
        assert not any(row["event"] == "runtime.restart" for row in server.events())
    assert server.token.encode() not in (tmp_path / "state.sqlite3").read_bytes()
    assert server.token not in (tmp_path / "server.log").read_text(encoding="utf-8")


def test_child_ignores_inherited_provider_and_actor_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKSIGHT_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "ignored-synthetic-provider-token")
    monkeypatch.setenv("DOCKSIGHT_API_TOKEN", "ignored-synthetic-operator-token")
    with (
        PersistentServer(tmp_path) as server,
        httpx.Client(base_url=server.origin, headers={"Authorization": f"Bearer {server.token}"}) as api,
    ):
        providers = api.get("/api/v1/model-providers").json()
        assert providers["default"] == {"provider": "ollama", "model": "qwen3.5:9b"}
        assert not next(row for row in providers["providers"] if row["id"] == "openai")["configured"]
        assert (
            api.get("/api/v1/hosts", headers={"Authorization": "Bearer ignored-synthetic-operator-token"}).status_code
            == 401
        )
