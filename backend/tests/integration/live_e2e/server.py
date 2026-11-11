import secrets
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
import uvicorn

from docksight.adapters.outbound.docker.hosts import HostConfig
from docksight.adapters.outbound.docker.runtime import DockerRuntime
from docksight.application.redaction import Redactor
from docksight.bootstrap import Settings, build_components
from docksight.domain.errors import DockSightError, ErrorKind
from docksight.domain.runtime import ContainerSnapshot, LogBatch, ResourceMetrics, StackSummary
from docksight.main import create_app
from tests.integration.live_e2e.lab import ComposeLab


def local_model_url(value: str) -> str:
    """Reject remote endpoints and credentials before any provider request in this local-only suite."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Live-e2e supports only loopback Ollama endpoints")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("The model endpoint must not contain credentials, paths, queries, or fragments")
    return value.rstrip("/")


def require_local_models(rows: list[dict[str, Any]], names: list[str]) -> None:
    """Reject missing models and local aliases that forward generation to a remote Ollama host."""
    installed = {row["name"]: row for row in rows}
    missing = set(names) - installed.keys()
    if missing:
        raise ValueError(f"Requested models are not installed: {', '.join(sorted(missing))}")
    for name in names:
        if installed[name].get("remote_model") or installed[name].get("remote_host"):
            raise ValueError(f"Remote/cloud models are outside this local-only suite: {name}")


class FixtureRuntime(DockerRuntime):
    """Use the real Docker adapter while restricting every read and mutation boundary to fixture identities."""

    def __init__(self, lab: ComposeLab) -> None:
        """Keep user workloads outside model-visible inventory and prohibit product mutations."""
        super().__init__((HostConfig(id="e2e", name="Live E2E"),), Redactor(), ("APP_ENV",), timeout=10)
        self.ids = frozenset(
            row.id for row in (*lab.containers.values(), *lab.peers.values(), *lab.standalone.values())
        )
        self.project = lab.project

    def _require_fixture(self, container_id: str) -> None:
        """Reject reads outside the exact containers created by this run."""
        if container_id not in self.ids:
            raise DockSightError(
                "fixture_scope_violation", "Resource is outside the live-e2e fixture", ErrorKind.FORBIDDEN
            )

    async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
        """Inspect exact owned IDs without enumerating unrelated host workloads."""
        return tuple([await self.inspect(host, container_id) for container_id in sorted(self.ids)])

    async def inspect(self, host: str, container_id: str) -> ContainerSnapshot:
        """Read an owned resource using production Docker mapping and redaction."""
        self._require_fixture(container_id)
        return await super().inspect(host, container_id)

    async def logs(self, host: str, container_id: str, lines: int, max_bytes: int) -> LogBatch:
        """Read real bounded logs only from an owned resource."""
        self._require_fixture(container_id)
        return await super().logs(host, container_id, lines, max_bytes)

    async def stats(self, host: str, container_id: str) -> ResourceMetrics:
        """Read actual metrics without granting access to other containers."""
        self._require_fixture(container_id)
        return await super().stats(host, container_id)

    async def stacks(self, host: str, kind: Literal["compose", "swarm"]) -> tuple[StackSummary, ...]:
        """Expose the Compose fixture namespace; this suite owns no Swarm resources."""
        return await super().stacks(host, kind) if kind == "compose" else ()

    async def restart(self, host: str, container_id: str) -> None:
        """Fail any unexpected attempt to execute a product action during diagnostic testing."""
        raise AssertionError("Live-e2e diagnoses must not execute restart")

    async def stop(self, host: str, container_id: str) -> None:
        """Fail any unexpected attempt to execute a product action during diagnostic testing."""
        raise AssertionError("Live-e2e diagnoses must not execute stop")


def _wait_server(server: uvicorn.Server, thread: threading.Thread, url: str) -> None:
    """Wait for readiness without generating a model response or reading operator credentials."""
    deadline = time.monotonic() + 15
    with httpx.Client(timeout=1, trust_env=False) as probe:
        while thread.is_alive() and time.monotonic() < deadline:
            try:
                response = probe.get(url + "/health/ready")
                if server.started and response.status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.05)
    raise RuntimeError("The isolated live-e2e API did not become ready")


@contextmanager
def live_api(lab: ComposeLab, model: str, model_url: str, origins: tuple[str, ...] = ()) -> Iterator[httpx.Client]:
    """Serve the actual application on an ephemeral loopback port with fresh in-memory credentials."""
    runtime = FixtureRuntime(lab)
    token = secrets.token_urlsafe(32)
    settings = Settings(
        state_backend="memory",
        _env_file=None,
        _env_prefix=f"E2E_{lab.owner}_",
        api_token=token,
        provider="ollama",
        model=model,
        model_base_url=model_url,
        model_api_key="",
        hosts_file=None,
        env_allowlist=("APP_ENV",),
        model_timeout=90,
        turn_timeout=240,
        log_lines=lab.case.log_limits[0],
        log_bytes=lab.case.log_limits[1],
        cors_origins=origins,
    )
    components = build_components(settings, reader=runtime, writer=runtime)
    components.closers.append(runtime.close)
    app = create_app(settings, components)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            _wait_server(server, thread, url)
            with httpx.Client(
                base_url=url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=260,
                trust_env=False,
            ) as api:
                yield api
        finally:
            server.should_exit = True
            thread.join(timeout=20)
            if thread.is_alive():
                server.force_exit = True
                thread.join(timeout=5)
                raise RuntimeError("The live-e2e API did not shut down cleanly")
