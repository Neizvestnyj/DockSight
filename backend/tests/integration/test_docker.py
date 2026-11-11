import asyncio
import json
import os
from time import monotonic, sleep
from uuid import uuid4

import docker
import pytest
from docker.models.containers import Container
from fastapi.testclient import TestClient

from docksight.adapters.outbound.docker.hosts import HostConfig
from docksight.adapters.outbound.docker.runtime import DockerRuntime
from docksight.application.ports.models import ModelReply
from docksight.application.redaction import Redactor
from docksight.application.views.schemas import ContainerStatusCard, DiagnosisResponse, LogAnomalyCard
from docksight.bootstrap import Settings, build_components
from docksight.domain.runtime import ContainerSnapshot
from docksight.main import create_app
from tests.fakes import ScriptedModel

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.getenv("DOCKSIGHT_TEST_DOCKER") != "1",
        reason="Set DOCKSIGHT_TEST_DOCKER=1",
    ),
]


@pytest.mark.parametrize("tty", [False, True], ids=["multiplexed", "tty"])
async def test_real_container_reads_redaction_and_mutations(tty: bool) -> None:
    """Exercise Docker reads and mutations when startup logs are delayed."""
    owner = str(uuid4())
    client = docker.from_env()
    container = client.containers.run(
        os.getenv("DOCKSIGHT_TEST_IMAGE", "python:3.12-alpine"),
        [
            "python",
            "-u",
            "-c",
            "import time; time.sleep(1); print('password=test-sentinel-9281'); time.sleep(300)",
        ],
        detach=True,
        tty=tty,
        name=f"docksight-test-{owner}",
        labels={"com.docksight.test": owner},
        environment={"DB_PASSWORD": "test-sentinel-9281", "APP_ENV": "test"},
    )
    runtime = DockerRuntime((HostConfig(id="local"),), Redactor(), ("APP_ENV",))
    try:
        item = await runtime.inspect("local", container.id)
        assert item.id == container.id
        assert item.state == "running"
        assert item.environment == (("APP_ENV", "test"),)
        async with asyncio.timeout(10):
            while True:
                logs = await runtime.logs("local", container.id, 20, 2048)
                if logs.entries:
                    break
                await asyncio.sleep(0.05)
        assert logs.entries
        assert "test-sentinel-9281" not in str(logs)
        stats = await runtime.stats("local", container.id)
        assert stats.memory_usage_bytes is not None
        await runtime.stop("local", container.id)
        assert (await runtime.inspect("local", container.id)).state == "exited"
        await runtime.restart("local", container.id)
        assert (await runtime.inspect("local", container.id)).state == "running"
    finally:
        await runtime.close()
        container.reload()
        if container.labels.get("com.docksight.test") == owner:
            container.remove(force=True)
        client.close()


def test_real_docker_http_diagnosis_and_confirmed_restart() -> None:
    """Diagnose automatically collected exact-container evidence before confirming a real restart."""
    owner = str(uuid4())
    client = docker.from_env()
    program = "\n".join(
        [
            "from pathlib import Path",
            "import time",
            "marker = Path('/tmp/started')",
            "if not marker.exists():",
            "    marker.touch()",
            "    print('DemoInitializationError: initial startup failed', flush=True)",
            "    raise SystemExit(1)",
            "time.sleep(300)",
        ]
    )
    container = client.containers.run(
        os.getenv("DOCKSIGHT_TEST_IMAGE", "python:3.12-alpine"),
        ["python", "-u", "-c", program],
        detach=True,
        name=f"docksight-test-{owner}",
        labels={"com.docksight.test": owner},
    )
    try:
        assert container.wait(timeout=10)["StatusCode"] == 1
        proposal = {
            "summary": "Initial startup failed; retry initialization",
            "uncertain": False,
            "evidence_ids": ["e1", "e2"],
            "widgets": [
                {"widget_type": "container_status", "evidence_ids": ["e1"]},
                {"widget_type": "log_anomalies", "evidence_ids": ["e2"]},
            ],
        }
        model = ScriptedModel([ModelReply("Ready"), ModelReply(json.dumps(proposal))])
        settings = Settings(
            state_backend="memory", api_token="integration-test-token-at-least-24-chars", _env_file=None
        )
        headers = {"Authorization": f"Bearer {settings.api_token.get_secret_value()}"}
        with TestClient(create_app(settings, build_components(settings, model=model))) as api:
            response = api.post(
                "/api/v1/chat/turns",
                headers=headers,
                json={"host": "local", "query": f"Inspect {container.id}"},
            )
            assert response.status_code == 200
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            assert events[-1]["type"] == "turn.completed", events[-1]
            answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
            assert answer["widgets"][0]["snapshot"]["state"] == "exited"
            logs = next(widget for widget in answer["widgets"] if widget["widget_type"] == "log_anomalies")
            assert logs["container_id"] == container.id
            assert logs["evidence_ids"] == ["e2"]
            assert any("DemoInitializationError" in entry["message"] for entry in logs["logs"]["entries"])
            action_id = answer["widgets"][0]["actions"][0]["id"]
            result = api.post(
                f"/api/v1/actions/{action_id}/execute",
                headers={**headers, "Idempotency-Key": "integration-restart"},
                json={"confirmed": True},
            )
            assert result.json()["state"] == "succeeded"
            assert (
                api.get(f"/api/v1/hosts/local/containers/{container.id}", headers=headers).json()["state"] == "running"
            )
    finally:
        container.reload()
        if container.labels.get("com.docksight.test") == owner:
            container.remove(force=True)
        client.close()


def _wait_health(container: Container, expected: str) -> None:
    """Bound fixture readiness waits while comparing actual Docker healthcheck results."""
    deadline = monotonic() + 15
    while monotonic() < deadline:
        container.reload()
        if container.attrs["State"].get("Health", {}).get("Status") == expected:
            return
        sleep(0.1)
    pytest.fail(f"Fixture health did not become {expected}")


def _assert_health_reads(api: TestClient, headers: dict[str, str], container_id: str, project: str) -> None:
    """Check exact-container and Compose projections without redefining process-running counts."""
    snapshot = api.get(f"/api/v1/hosts/local/containers/{container_id}", headers=headers).json()
    assert snapshot["state"] == "running" and snapshot["health"] == "unhealthy"
    assert snapshot["restart_count"] == 0 and not snapshot["oom_killed"]
    groups = api.get("/api/v1/hosts/local/stacks?kind=compose", headers=headers).json()
    group = next(row for row in groups if row["name"] == project)
    assert group["total"] == group["running"] == 1
    assert group["members"][0]["health"] == "unhealthy"


def _diagnose_unhealthy(api: TestClient, headers: dict[str, str], project: str) -> ContainerSnapshot:
    """Require server-owned state and log cards even when the model selects no detail widgets."""
    response = api.post(
        "/api/v1/chat/turns",
        headers=headers,
        json={"host": "local", "query": "Check this project", "group": {"kind": "compose", "name": project}},
    )
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "turn.completed", events[-1]
    answer = DiagnosisResponse.model_validate(
        next(event["answer"] for event in events if event["type"] == "answer.ready")
    )
    status = next(widget for widget in answer.widgets if isinstance(widget, ContainerStatusCard))
    assert status.snapshot.state == "running"
    assert status.snapshot.health == "unhealthy"
    assert answer.group is not None
    assert answer.group.logs[0].state == "collected"
    assert any(isinstance(widget, LogAnomalyCard) for widget in answer.widgets)
    return status.snapshot


def test_real_running_unhealthy_container_reaches_api_evidence_and_recovers() -> None:
    """Keep process counts, health failures, model observations, and historical evidence distinct."""
    owner = str(uuid4())
    project = f"docksight-health-{owner}"
    client = docker.from_env(timeout=5)
    container = client.containers.run(
        os.getenv("DOCKSIGHT_TEST_IMAGE", "python:3.12-alpine"),
        ["python", "-u", "-c", "import time; print('Probe failed while process is running'); time.sleep(300)"],
        detach=True,
        name=project,
        labels={"com.docksight.test": owner, "com.docker.compose.project": project},
        healthcheck={
            "test": ["CMD-SHELL", "test -f /tmp/healthy"],
            "interval": 1000000000,
            "timeout": 1000000000,
            "retries": 1,
        },
    )
    try:
        _wait_health(container, "unhealthy")
        model = ScriptedModel(
            [
                ModelReply("Ready"),
                ModelReply(
                    json.dumps(
                        {
                            "summary": "The process is running but its healthcheck failed; the cause is unknown.",
                            "uncertain": True,
                            "evidence_ids": ["e1"],
                            "widgets": [],
                        }
                    )
                ),
            ]
        )
        settings = Settings(state_backend="memory", api_token="health-integration-test-token-24", _env_file=None)
        headers = {"Authorization": "Bearer health-integration-test-token-24"}
        with TestClient(create_app(settings, build_components(settings, model=model))) as api:
            _assert_health_reads(api, headers, container.id, project)
            original = _diagnose_unhealthy(api, headers, project)
            collected = next(message for message in model.requests[0][0] if message.role == "tool")
            observations = json.loads(collected.content)["observations"]
            assert any(row["kind"] == "container" and row["data"]["health"] == "unhealthy" for row in observations)
            assert container.exec_run(["touch", "/tmp/healthy"]).exit_code == 0
            _wait_health(container, "healthy")
            current = api.get(f"/api/v1/hosts/local/containers/{container.id}", headers=headers).json()
            assert current["health"] == "healthy" and current["state"] == "running"
            assert original.health == "unhealthy"
    finally:
        container.reload()
        if container.labels.get("com.docksight.test") == owner:
            container.remove(force=True)
        client.close()
