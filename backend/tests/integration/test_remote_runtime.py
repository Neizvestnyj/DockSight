import os

import pytest

from docksight.adapters.outbound.docker.hosts import load_hosts
from docksight.adapters.outbound.docker.runtime import DockerRuntime
from docksight.application.redaction import Redactor

pytestmark = [
    pytest.mark.remote,
    pytest.mark.skipif(
        os.getenv("DOCKSIGHT_TEST_REMOTE") != "1",
        reason="Set DOCKSIGHT_TEST_REMOTE=1",
    ),
]


async def test_configured_ssh_or_mtls_host_supports_bounded_reads() -> None:
    configs = load_hosts(os.environ["DOCKSIGHT_HOSTS_FILE"])
    host_id = os.environ["DOCKSIGHT_TEST_HOST"]
    host = next(item for item in configs if item.id == host_id)
    assert host.url and host.url.startswith(("ssh://", "tcp://")), "Select an SSH or mTLS host"
    runtime = DockerRuntime(configs, Redactor())
    try:
        rows = await runtime.containers(host_id)
        if rows:
            item = await runtime.inspect(host_id, rows[0].id)
            assert item.host == host_id
            assert item.id == rows[0].id
            logs = await runtime.logs(host_id, item.id, 5, 1024)
            assert len(logs.entries) <= 5
            await runtime.stats(host_id, item.id)
    finally:
        await runtime.close()
