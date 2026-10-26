import json
import os
from uuid import uuid4

import docker
import pytest
from fastapi.testclient import TestClient

from docksight.adapters.outbound.docker.hosts import HostConfig
from docksight.adapters.outbound.docker.runtime import DockerRuntime
from docksight.application.ports.models import ModelReply, ToolCall
from docksight.application.redaction import Redactor
from docksight.bootstrap import Settings, build_components
from docksight.main import create_app
from tests.fakes import ScriptedModel

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.getenv("DOCKSIGHT_TEST_DOCKER") != "1",
        reason="Set DOCKSIGHT_TEST_DOCKER=1",
    ),
]


async def test_real_container_reads_redaction_and_mutations() -> None:
    owner = str(uuid4())
    client = docker.from_env()
    container = client.containers.run(
        os.getenv("DOCKSIGHT_TEST_IMAGE", "python:3.12-alpine"),
        [
            "python",
            "-u",
            "-c",
            "import time; print('password=test-sentinel-9281'); time.sleep(300)",
        ],
        detach=True,
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
        logs = await runtime.logs("local", container.id, 20, 2048)
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
            "evidence_ids": ["e1", "e3"],
            "widgets": [
                {"widget_type": "container_status", "evidence_ids": ["e1"]},
                {"widget_type": "log_anomalies", "evidence_ids": ["e3"]},
            ],
        }
        model = ScriptedModel(
            [
                ModelReply(
                    "",
                    (
                        ToolCall("c1", "inspect_container", {"container_id": container.id}),
                        ToolCall("c2", "get_container_logs", {"container_id": container.id}),
                    ),
                ),
                ModelReply("Ready"),
                ModelReply(json.dumps(proposal)),
            ]
        )
        settings = Settings(api_token="integration-test-token-at-least-24-chars", _env_file=None)
        headers = {"Authorization": f"Bearer {settings.api_token.get_secret_value()}"}
        with TestClient(create_app(settings, build_components(settings, model=model))) as api:
            response = api.post(
                "/api/v1/chat/turns",
                headers=headers,
                json={"host": "local", "query": f"Inspect {container.id}"},
            )
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
            assert answer["widgets"][0]["snapshot"]["state"] == "exited"
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
