import asyncio
import json
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from docksight.application.ports.models import ModelMessage, ModelReply, ToolSpec
from docksight.bootstrap import Settings, build_components
from docksight.domain.diagnostics import JsonObject
from docksight.main import create_app
from tests.fakes import FakeRuntime
from tests.http_server import http_server

TOKEN = "observer-token-at-least-24-characters"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


class BlockingModel:
    """Keep accepted generation in flight while actual HTTP observers attach and disconnect."""

    def __init__(self) -> None:
        """Expose thread-safe test barriers without adding HTTP control routes."""
        self.started = threading.Event()
        self.release = asyncio.Event()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.calls = 0

    def unblock(self) -> None:
        """Release generation from the HTTP test thread through its owning event loop."""
        assert self.loop is not None
        self.loop.call_soon_threadsafe(self.release.set)

    async def complete(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec] = (),
        schema: JsonObject | None = None,
    ) -> ModelReply:
        """Block evidence generation until released, then return a valid bounded answer."""
        self.calls += 1
        self.loop = asyncio.get_running_loop()
        self.started.set()
        await self.release.wait()
        return ModelReply(
            '{"summary":"Retained answer","uncertain":true,"evidence_ids":[],"widgets":[]}'
            if schema is not None
            else "Ready"
        )


def app_factory(path: Path, model: BlockingModel):
    """Bind all server state to a temporary file and the allocated first-party origin."""

    def create(origin: str) -> FastAPI:
        """Build one production-wired server with deterministic runtime and model ports."""
        settings = Settings(
            api_token=TOKEN, state_path=path, browser_origin=origin, cookie_secure=False, _env_file=None
        )
        runtime = FakeRuntime()
        components = build_components(settings, reader=runtime, writer=runtime, model=model)
        components.runner.shutdown_timeout = 0.01
        return create_app(settings, components)

    return create


def frame(lines: Iterator[str]) -> dict:
    """Read one SSE JSON data frame while skipping event names and heartbeats."""
    for line in lines:
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError("Stream closed before a data frame")


def accept(api: httpx.Client) -> tuple[str, str]:
    """Create an owned investigation and accept one question before observation."""
    identity = str(uuid4())
    assert api.post("/api/v1/investigations", json={"id": identity, "host": "local"}).status_code == 201
    response = api.post(
        f"/api/v1/investigations/{identity}/turns",
        json={
            "kind": "question",
            "submission_id": str(uuid4()),
            "expected_revision": 0,
            "query": "Inspect",
        },
    )
    assert response.status_code == 202
    return identity, response.json()["snapshot"]["id"]


def wait_terminal(api: httpx.Client, turn_id: str) -> dict:
    """Poll saved state with a bounded deadline without triggering generation or replay."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        saved = api.get(f"/api/v1/turns/{turn_id}").json()
        if saved["state"] != "running":
            return saved
        time.sleep(0.01)
    raise AssertionError("Retained diagnostic did not settle")


def test_snapshot_disconnect_observer_capacity_and_repeat_reads_keep_one_job(tmp_path: Path) -> None:
    model = BlockingModel()
    with (
        http_server(app_factory(tmp_path / "state.sqlite3", model)) as origin,
        httpx.Client(
            base_url=origin,
            headers=HEADERS,
            timeout=15,
        ) as api,
    ):
        identity, turn_id = accept(api)
        assert model.started.wait(2)
        live_lines: list[Iterator[str]] = []
        with ExitStack() as observers:
            for _ in range(4):
                response = observers.enter_context(api.stream("GET", f"/api/v1/turns/{turn_id}/events"))
                assert response.status_code == 200
                live_lines.append(response.iter_lines())
                assert frame(live_lines[-1])["id"] == turn_id
            with api.stream("GET", f"/api/v1/turns/{turn_id}/events") as denied:
                assert denied.status_code == 409
                assert json.loads(denied.read())["code"] == "turn_observer_capacity"
            assert api.delete(f"/api/v1/investigations/{identity}").json()["code"] == "turn_busy"
        assert api.get(f"/api/v1/turns/{turn_id}").json()["state"] == "running"
        assert api.get(f"/api/v1/investigations/{identity}").json()["active_turn_id"] == turn_id
        assert model.calls == 1
        model.unblock()
        saved = wait_terminal(api, turn_id)
        assert saved["state"] == "completed"
        for _ in range(3):
            assert api.get(f"/api/v1/turns/{turn_id}/events").status_code == 200
        assert model.calls == 2


@pytest.mark.parametrize("stream_kind", ["snapshot", "legacy"])
def test_revoked_cookie_detaches_real_observer_without_cancelling_job(tmp_path: Path, stream_kind: str) -> None:
    model = BlockingModel()
    with (
        http_server(app_factory(tmp_path / "state.sqlite3", model)) as origin,
        httpx.Client(
            base_url=origin,
            headers=HEADERS,
            timeout=15,
        ) as api,
        httpx.Client(base_url=origin, timeout=15) as browser,
    ):
        login = browser.post("/api/v1/auth/login", headers={**HEADERS, "Origin": origin}, json={})
        assert login.status_code == 200
        unsafe = {"Origin": origin, "X-CSRF-Token": login.json()["csrf_token"]}
        if stream_kind == "snapshot":
            _, turn_id = accept(api)
            method, path, options = "GET", f"/api/v1/turns/{turn_id}/events", {}
        else:
            turn_id = ""
            method, path, options = (
                "POST",
                "/api/v1/chat/turns",
                {
                    "headers": unsafe,
                    "json": {"host": "local", "query": "Inspect"},
                },
            )
        with browser.stream(method, path, **options) as response:
            assert response.status_code == 200
            lines = response.iter_lines()
            first = frame(lines)
            turn_id = first["id"] if stream_kind == "snapshot" else first["turn_id"]
            assert model.started.wait(2)
            assert browser.post("/api/v1/auth/logout", headers=unsafe, json={}).status_code == 204
            list(lines)
        assert api.get(f"/api/v1/turns/{turn_id}").json()["state"] == "running"
        assert model.calls == 1
        model.unblock()
        assert wait_terminal(api, turn_id)["state"] == "completed"


def test_legacy_disconnect_keeps_accepted_work_and_submission_receipt(tmp_path: Path) -> None:
    model = BlockingModel()
    body = {"host": "local", "query": "Inspect", "submission_id": str(uuid4())}
    with (
        http_server(app_factory(tmp_path / "state.sqlite3", model)) as origin,
        httpx.Client(
            base_url=origin,
            headers=HEADERS,
            timeout=15,
        ) as api,
    ):
        with api.stream("POST", "/api/v1/chat/turns", json=body) as response:
            assert response.status_code == 200
            first = frame(response.iter_lines())
            assert model.started.wait(2)
        turn_id = first["turn_id"]
        assert api.get(f"/api/v1/turns/{turn_id}").json()["state"] == "running"
        model.unblock()
        assert wait_terminal(api, turn_id)["state"] == "completed"
        replay = api.post("/api/v1/chat/turns", json=body)
        assert frame(iter(replay.text.splitlines()))["turn_id"] == turn_id
        assert model.calls == 2


def test_explicit_stop_saves_one_terminal_winner_and_does_not_restart_on_observation(tmp_path: Path) -> None:
    model = BlockingModel()
    with (
        http_server(app_factory(tmp_path / "state.sqlite3", model)) as origin,
        httpx.Client(
            base_url=origin,
            headers=HEADERS,
            timeout=15,
        ) as api,
    ):
        _, turn_id = accept(api)
        assert model.started.wait(2)
        stopped = api.post(f"/api/v1/turns/{turn_id}/cancel")
        assert stopped.status_code == 200 and stopped.json()["state"] == "stopped"
        assert api.post(f"/api/v1/turns/{turn_id}/cancel").json() == stopped.json()
        observed = api.get(f"/api/v1/turns/{turn_id}/events")
        assert frame(iter(observed.text.splitlines()))["state"] == "stopped"
        assert model.calls == 1
