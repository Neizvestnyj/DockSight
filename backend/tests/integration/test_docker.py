import os
from uuid import uuid4

import docker
import pytest

from docksight.adapters.outbound.docker.hosts import HostConfig
from docksight.adapters.outbound.docker.runtime import DockerRuntime
from docksight.application.redaction import Redactor

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
