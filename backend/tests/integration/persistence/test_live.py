import os
import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import docker
import httpx
import pytest

from tests.integration.persistence.live import create, operate, owned
from tests.integration.persistence.process import PersistentServer

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(os.getenv("DOCKSIGHT_PERSISTENCE_LIVE") != "1", reason="Set DOCKSIGHT_PERSISTENCE_LIVE=1"),
]


def prepare(api: httpx.Client, container_id: str) -> str:
    """Prepare a fresh exact-target restart through the real authenticated API."""
    response = api.post("/api/v1/actions", json={"host": "local", "container_id": container_id, "operation": "restart"})
    assert response.status_code == 201
    return response.json()["id"]


def test_live_restart_lost_delivery_retained_key_and_post_docker_crash_block(tmp_path: Path) -> None:
    metadata = create(tmp_path)
    try:
        with (
            PersistentServer(tmp_path) as server,
            httpx.Client(
                base_url=server.origin, headers={"Authorization": f"Bearer {server.token}"}, timeout=45
            ) as api,
            closing(docker.from_env(timeout=10)) as client,
        ):
            container = owned(client, tmp_path)
            original_start = container.attrs["State"]["StartedAt"]
            first = prepare(api, metadata["id"])
            first_path = f"/api/v1/actions/{first}"
            (tmp_path / "delivery.block").touch()
            with socket.create_connection(("127.0.0.1", server.port), timeout=10) as lost:
                body = b'{"confirmed":true}'
                headers = (
                    f"POST {first_path}/execute HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\n"
                    f"Authorization: Bearer {server.token}\r\nIdempotency-Key: live-one-key\r\n"
                    f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
                )
                lost.sendall(headers.encode() + body)
                server.wait_file("delivery.entered", timeout=30)
                assert api.get(first_path).json()["state"] == "succeeded"
            (tmp_path / "delivery.block").unlink()
            container.reload()
            assert container.attrs["State"]["StartedAt"] != original_start
            first_start = container.attrs["State"]["StartedAt"]
            server.restart()
            assert api.get(first_path).json()["state"] == "succeeded"
            replay = api.post(
                first_path + "/execute", headers={"Idempotency-Key": "live-one-key"}, json={"confirmed": True}
            )
            assert replay.status_code == 200 and replay.json()["state"] == "succeeded"
            container.reload()
            assert container.attrs["State"]["StartedAt"] == first_start
            second = prepare(api, metadata["id"])
            second_path = f"/api/v1/actions/{second}"
            (tmp_path / "mutation.block").touch()
            with ThreadPoolExecutor(max_workers=1) as pool:
                execution = pool.submit(
                    api.post,
                    second_path + "/execute",
                    headers={"Idempotency-Key": "live-crash-key"},
                    json={"confirmed": True},
                )
                server.wait_file("mutation.entered", timeout=30)
                container.reload()
                assert container.attrs["State"]["StartedAt"] != first_start
                assert api.get(second_path).json()["state"] == "running"
                server.restart()
                with pytest.raises(httpx.HTTPError):
                    execution.result(timeout=10)
            for _ in range(2):
                assert api.get(second_path).json()["state"] == "indeterminate"
                replay = api.post(
                    second_path + "/execute", headers={"Idempotency-Key": "live-crash-key"}, json={"confirmed": True}
                )
                assert replay.status_code == 200 and replay.json()["state"] == "indeterminate"
                candidate = prepare(api, metadata["id"])
                denied = api.post(
                    f"/api/v1/actions/{candidate}/execute",
                    headers={"Idempotency-Key": "blocked-key"},
                    json={"confirmed": True},
                )
                assert denied.status_code == 409 and denied.json()["code"] == "target_indeterminate"
                server.restart()
            assert sum(row["event"] == "runtime.restart" for row in server.events()) == 2
    finally:
        operate(tmp_path, "remove")
