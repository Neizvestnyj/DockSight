import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Final, Self

import httpx

TOKEN: Final = "persistence-alice-test-token-0001"
BOB_TOKEN: Final = "persistence-bob-test-token-00002"


class PersistentServer:
    """Own one HTTP child and its temporary SQLite and IPC directory."""

    def __init__(self, directory: Path, *, origin: str | None = None, port: int = 0) -> None:
        """Retain the test-owned directory for the child process."""
        self.directory = directory
        self.public_origin = origin
        self.port = port
        self.origin = ""
        self.token = TOKEN
        self.process: subprocess.Popen[bytes] | None = None
        self.output: Any = None

    @property
    def pid(self) -> int:
        """Expose the owned child identity for separate-process assertions."""
        assert self.process is not None
        return self.process.pid

    def __enter__(self) -> Self:
        """Start the real HTTP child before exposing the fixture."""
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        """Close only the child owned by this fixture."""
        self.stop()

    def start(self) -> None:
        """Launch Python directly with hidden Windows ownership and bounded readiness."""
        self.directory.mkdir(parents=True, exist_ok=True)
        ready = self.directory / "ready.json"
        ready.unlink(missing_ok=True)
        backend = Path(__file__).resolve().parents[3]
        self.output = (self.directory / "server.log").open("ab")
        arguments = [
            sys.executable,
            "-m",
            "tests.integration.persistence.server",
            "--directory",
            str(self.directory),
            "--port",
            str(self.port),
        ]
        if self.public_origin is not None:
            arguments.extend(("--origin", self.public_origin))
        self.process = subprocess.Popen(
            arguments,
            cwd=backend.parent,
            env={**os.environ, "PYTHONPATH": os.pathsep.join((str(backend / "src"), str(backend)))},
            stdout=self.output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        try:
            self.wait_file("ready.json")
            self.origin = json.loads(ready.read_text(encoding="utf-8"))["origin"]
            self.port = int(self.origin.rsplit(":", 1)[1])
        except BaseException:
            self.stop()
            raise

    def wait_file(self, name: str, timeout: float = 20) -> None:
        """Wait for a test-owned IPC marker without exposing production control routes."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (self.directory / name).exists():
                return
            if self.process is not None and self.process.poll() is not None:
                raise AssertionError((self.directory / "server.log").read_text(encoding="utf-8"))
            time.sleep(0.02)
        raise AssertionError(f"Child did not reach {name}")

    def stop(self) -> None:
        """Terminate and reap only this fixture's child, retaining files for inspection."""
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=10)
        if self.output is not None:
            self.output.close()

    def restart(self) -> None:
        """Crash and restart against the same SQLite file and allocated loopback port."""
        self.stop()
        self.start()

    def events(self) -> list[dict[str, Any]]:
        """Read only content-free correlation events written by test ports."""
        path = self.directory / "events.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def wait_turn(self, api: httpx.Client, turn_id: str, timeout: float = 10) -> dict[str, Any]:
        """Poll authoritative saved reads until a terminal state without submitting again."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = api.get(f"/api/v1/turns/{turn_id}")
            response.raise_for_status()
            saved = response.json()
            if saved["state"] != "running":
                return saved
            time.sleep(0.02)
        raise AssertionError("Turn did not settle before the bounded fixture deadline")
