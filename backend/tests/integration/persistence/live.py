import argparse
import json
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Final
from uuid import uuid4

import docker
from docker.models.containers import Container

LABEL: Final = "com.docksight.persistence-test"
IMAGE: Final = "python:3.12-alpine"
PROGRAM: Final = (
    "import pathlib,time; p=pathlib.Path('/tmp/evidence'); "
    "p.write_text('Fixture revision one') if not p.exists() else None\n"
    "while True: print(p.read_text(), flush=True); time.sleep(0.2)"
)


def create(directory: Path) -> dict[str, Any]:
    """Create one uniquely labeled container from an already installed image without pulling."""
    owner = uuid4().hex
    client = docker.from_env(timeout=10)
    try:
        client.images.get(IMAGE)
        container = client.containers.run(
            IMAGE,
            ["python", "-u", "-c", PROGRAM],
            detach=True,
            name=f"docksight-persistence-{owner}",
            labels={LABEL: owner},
        )
        metadata = {"id": container.id, "owner": owner, "name": container.name}
        (directory / "live.json").write_text(json.dumps(metadata), encoding="utf-8")
        return metadata
    finally:
        client.close()


def owned(client: docker.DockerClient, directory: Path) -> Container:
    """Verify the exact saved ID and ownership label before any fixture operation."""
    metadata = json.loads((directory / "live.json").read_text(encoding="utf-8"))
    container = client.containers.get(metadata["id"])
    if container.id != metadata["id"] or container.labels.get(LABEL) != metadata["owner"]:
        raise AssertionError("Docker resource is outside this fixture's ownership")
    return container


def operate(directory: Path, operation: str) -> None:
    """Update or remove only the exact fixture resource after checking its ownership."""
    client = docker.from_env(timeout=10)
    try:
        container = owned(client, directory)
        if operation == "remove":
            container.remove(force=True)
        elif operation == "update":
            result = container.exec_run(
                ["python", "-c", "from pathlib import Path; Path('/tmp/evidence').write_text('Fixture revision two')"]
            )
            if result.exit_code != 0:
                raise AssertionError("Fixture evidence update failed")
            deadline = monotonic() + 5
            while monotonic() < deadline:
                if b"Fixture revision two" in container.logs(tail=1):
                    return
                sleep(0.02)
            raise AssertionError("Fixture did not publish fresh evidence")
        else:
            raise ValueError("Unknown fixture operation")
    finally:
        client.close()


def main() -> None:
    """Expose test-owned lifecycle IPC without installing any application HTTP endpoints."""
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("create", "update", "remove"))
    parser.add_argument("--directory", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.operation == "create":
        create(arguments.directory)
    else:
        operate(arguments.directory, arguments.operation)


if __name__ == "__main__":
    main()
