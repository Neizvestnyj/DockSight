import json
import os
import time
from uuid import uuid4

import docker
import pytest

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.getenv("DOCKSIGHT_TEST_DOCKER") != "1" or not os.getenv("DOCKSIGHT_TEST_BACKEND_IMAGE"),
        reason="Set DOCKSIGHT_TEST_DOCKER=1 and DOCKSIGHT_TEST_BACKEND_IMAGE",
    ),
]


def test_built_image_starts_as_non_root_and_serves_health() -> None:
    """Verify built image starts as non root and serves health."""
    owner = str(uuid4())
    client = docker.from_env()
    container = client.containers.run(
        os.environ["DOCKSIGHT_TEST_BACKEND_IMAGE"],
        detach=True,
        name=f"docksight-image-test-{owner}",
        labels={"com.docksight.test": owner},
        environment={"DOCKSIGHT_API_TOKEN": "image-smoke-token-at-least-24-chars"},
    )
    try:
        result = None
        for _ in range(30):
            result = container.exec_run(
                [
                    "python",
                    "-c",
                    "import urllib.request; "
                    "url='http://127.0.0.1:8000/health/live'; "
                    "data=urllib.request.urlopen(url, timeout=1).read(); "
                    "print(data.decode())",
                ]
            )
            if result.exit_code == 0:
                break
            container.reload()
            assert container.status == "running", container.logs().decode()
            time.sleep(0.25)
        assert result is not None and result.exit_code == 0, container.logs().decode()
        assert json.loads(result.output)["status"] == "ok"
        assert container.exec_run(["id", "-u"]).output.strip() != b"0"
    finally:
        container.reload()
        if container.labels.get("com.docksight.test") == owner:
            container.remove(force=True)
        client.close()
