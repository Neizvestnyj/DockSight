import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

from docker.constants import DEFAULT_NPIPE, DEFAULT_UNIX_SOCKET
from docker.errors import DockerException
from docker.models.containers import Container

from docksight.adapters.outbound.docker.hosts import HostConfig, connect
from tests.integration.live_e2e.cases import FOLLOW_UP_CASES, FOLLOW_UP_NOISY_CASE, Case

ROOT: Final = Path(__file__).resolve().parents[4]
OWNER_LABEL: Final = "com.docksight.e2e"
FAILURES: Final = {
    "backend": (1, False, "DatabaseConnectionError"),
    "grafana": (1, False, "could not find Chat Id"),
    "oom": (137, True, "Starting a 256 MiB allocation"),
    "unknown": (137, False, "Worker ended without recording"),
}


def require_owner(labels: dict[str, str], owner: str) -> None:
    """Refuse cleanup when an observed resource is not owned by this exact run."""
    if labels.get(OWNER_LABEL) != owner:
        raise RuntimeError("Refusing to remove a resource not owned by this live-e2e run")


def _terminate(process: subprocess.Popen[str]) -> None:
    """Stop an owned CLI process tree before cleaning resources its descendants could still use."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
                check=True,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def run_command(
    arguments: list[str], environment: dict[str, str], timeout: float = 240, label: str = "Compose setup"
) -> None:
    """Bound CLI execution and terminate its plugin descendants on timeout or interruption."""
    with subprocess.Popen(
        arguments,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=os.name != "nt",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException:
            _terminate(process)
            raise
        if process.returncode:
            raise RuntimeError(f"{label} failed: {(stdout + stderr)[-6000:]}")


class ComposeLab:
    """Create uniquely labelled real workloads and remove only resources belonging to this run."""

    def __init__(self, case: Case) -> None:
        """Allocate an unguessable project without creating any Docker resource yet."""
        self.case = case
        self.owner = uuid4().hex
        self.project = f"vintoria-infra-e2e-{self.owner[:12]}a"
        self.peer_project = self.project[:-1] + "b" if case.spelling == "ambiguous" else f"other-e2e-{self.owner[:12]}"
        self.client = connect(HostConfig(id="e2e"), timeout=10)
        self.containers: dict[str, Container] = {}
        self.peers: dict[str, Container] = {}

    def start(self) -> None:
        """Start only the selected services and wait for their specified observable failure states."""
        self._compose(self.project, self.case.services)
        self.containers = {row.labels["com.docker.compose.service"]: row for row in self._owned_containers()}
        if set(self.containers) != set(self.case.services):
            raise RuntimeError("Compose did not create the exact requested service set")
        self._wait_ready()
        if self.case.group:
            self._start_peer()

    def _start_peer(self) -> None:
        """Create a separate dependency namespace, optionally with a colliding container name and noisy logs."""
        service = "database" if self.case == FOLLOW_UP_NOISY_CASE else "backend"
        self._compose(self.peer_project, (service,))
        self.peers = {
            row.id: row for row in self._owned_containers() if row.labels["com.docker.compose.project"] != self.project
        }
        if len(self.peers) != 1:
            raise RuntimeError("Compose did not create the exact peer service set")
        self._wait_ready({service: next(iter(self.peers.values()))})
        if self.case in FOLLOW_UP_CASES:
            peer = next(iter(self.peers.values()))
            require_owner(peer.labels, self.owner)
            peer.rename(self.peer_project)
            peer.reload()

    def _compose(self, project: str, services: tuple[str, ...]) -> None:
        """Create one uniquely owned namespace from the real Compose fixture definition."""
        if self.client.containers.list(all=True, filters={"label": f"com.docker.compose.project={project}"}):
            raise RuntimeError("Refusing to reuse an existing Compose project")
        environment = {**os.environ, "DOCKSIGHT_E2E_OWNER": self.owner}
        environment.pop("DOCKER_CONTEXT", None)
        default_host = DEFAULT_NPIPE if os.name == "nt" else DEFAULT_UNIX_SOCKET.replace("http+unix:", "unix:")
        docker_host = environment.get("DOCKER_HOST") or default_host
        run_command(
            [
                "docker",
                "--host",
                docker_host,
                "compose",
                "--env-file",
                os.devnull,
                "-f",
                str(ROOT / "examples/live-e2e/compose.yaml"),
                "-p",
                project,
                "up",
                "-d",
                "--pull",
                "missing",
                *services,
            ],
            environment,
        )

    def _owned_containers(self) -> list[Container]:
        """Read only resources carrying this run's unguessable ownership label, across its two namespaces."""
        return self.client.containers.list(all=True, filters={"label": f"{OWNER_LABEL}={self.owner}"})

    def _wait_ready(self, selected: dict[str, Container] | None = None) -> None:
        """Bound startup waits and preserve real Docker evidence when a fixture cannot reach its required state."""
        deadline = time.monotonic() + 90
        rows = self.containers if selected is None else selected
        while time.monotonic() < deadline:
            for row in rows.values():
                row.reload()
            if all(self._ready(name, row) for name, row in rows.items()):
                self._validate_failures()
                return
            time.sleep(0.2)
        states = {name: row.attrs["State"]["Status"] for name, row in rows.items()}
        raise RuntimeError(f"Fixture readiness timed out: {states}")

    def _validate_failures(self) -> None:
        """Fail fixture setup when Docker or logs show a different failure than the scenario requires."""
        for name, row in self.containers.items():
            if name not in FAILURES:
                continue
            exit_code, oom, marker = FAILURES[name]
            state = row.attrs["State"]
            output = row.logs(tail=100).decode("utf-8", errors="replace")
            if (state["ExitCode"], state["OOMKilled"]) != (exit_code, oom) or marker not in output:
                raise RuntimeError(f"Unexpected fixture failure for {name}; required workload was not reproduced")

    def _ready(self, name: str, row: Container) -> bool:
        """Check Docker facts rather than assuming that detached startup means application readiness."""
        state = row.attrs["State"]
        if name in {"backend", "grafana", "oom", "unknown"}:
            return state["Status"] == "exited"
        if name == "crash":
            return row.attrs["RestartCount"] >= 2
        if name in {"logs", "database"}:
            return state["Status"] == "running" and row.exec_run(["test", "-f", "/tmp/ready"]).exit_code == 0
        return state.get("Health", {}).get("Status") == "healthy"

    def facts(self) -> dict[str, Any]:
        """Record only selected runtime facts, never raw inspect documents or environment secrets."""
        return {
            name: {
                "id": row.id,
                "name": row.name,
                "image": row.image.id,
                "state": row.attrs["State"]["Status"],
                "exit_code": row.attrs["State"]["ExitCode"],
                "oom_killed": row.attrs["State"]["OOMKilled"],
                "restart_count": row.attrs["RestartCount"],
            }
            for name, row in self.containers.items()
        }

    def close(self) -> None:
        """Clean partial setup as well as successful runs, checking ownership before each removal."""
        failures: list[Exception] = []
        try:
            self._remove_containers(failures)
            self._remove_networks(failures)
        finally:
            self.client.close()
        if failures:
            raise ExceptionGroup("Live-e2e cleanup was incomplete", failures)

    def _remove_containers(self, failures: list[Exception]) -> None:
        """Attempt every owned container removal even after an earlier SDK failure."""
        try:
            rows = self._owned_containers()
        except DockerException as exc:
            failures.append(exc)
            return
        for row in rows:
            try:
                require_owner(row.labels, self.owner)
                row.remove(force=True, v=True)
            except (DockerException, RuntimeError) as exc:
                failures.append(exc)

    def _remove_networks(self, failures: list[Exception]) -> None:
        """Attempt owned network cleanup and surface every failure without touching another project's resources."""
        try:
            networks = self.client.networks.list(filters={"label": f"{OWNER_LABEL}={self.owner}"})
        except DockerException as exc:
            failures.append(exc)
            return
        for network in networks:
            try:
                require_owner(network.attrs.get("Labels") or {}, self.owner)
                network.remove()
            except (DockerException, RuntimeError) as exc:
                failures.append(exc)
