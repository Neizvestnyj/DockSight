import asyncio
from collections.abc import Callable, Iterator
from contextlib import closing
from typing import Any, Final, Literal, Protocol, cast

from docker.errors import DockerException, NotFound
from paramiko import SSHException
from requests import RequestException

from docksight.adapters.outbound.docker.groups import SwarmAPI, compose_stacks, swarm_stacks
from docksight.adapters.outbound.docker.hosts import HostConfig, connect
from docksight.adapters.outbound.docker.mapping import map_container, map_metrics, parse_logs
from docksight.application.redaction import Redactor
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import (
    ContainerSnapshot,
    Host,
    LogBatch,
    ResourceMetrics,
    StackSummary,
)

MAX_LOG_SCAN_BYTES: Final = 8 * 1024 * 1024


class LogStream(Protocol):
    """Describe a closeable stream of Docker log bytes."""

    def __iter__(self) -> Iterator[bytes]:
        """Yield log chunks while the underlying SDK response remains open."""
        ...

    def close(self) -> None:
        """Release the underlying streaming response."""
        ...


class DockerAPI(SwarmAPI, Protocol):
    """Describe the low-level SDK surface whose upstream stubs are incomplete."""

    def ping(self) -> bool:
        """Check the engine connection without reading container inventory."""
        ...

    def inspect_container(self, container: str) -> dict[str, Any]:
        """Read the raw inspect document for one container."""
        ...

    def containers(self, *, all: bool, limit: int) -> list[dict[str, Any]]:
        """List containers within the requested inventory limit."""
        ...

    def logs(self, container: str, *, tail: int, timestamps: bool, stream: bool, follow: bool) -> LogStream:
        """Open a bounded-tail log stream without following new output."""
        ...

    def stats(self, container: str, *, stream: bool) -> dict[str, Any]:
        """Read a container's raw resource counters."""
        ...

    def restart(self, container: str, *, timeout: int) -> None:
        """Restart the exact container with a bounded stop grace period."""
        ...

    def stop(self, container: str, *, timeout: int) -> None:
        """Stop the exact container with a bounded grace period."""
        ...


class DockerRuntime:
    """Adapt configured Docker engines to bounded runtime read and mutation ports."""

    def __init__(
        self,
        hosts: tuple[HostConfig, ...],
        redactor: Redactor,
        env_allowlist: tuple[str, ...] = (),
        timeout: float = 15,
    ) -> None:
        """Configure host resolution, redaction, timeouts, and worker capacity."""
        self._hosts = {host.id: host for host in hosts}
        self._redactor = redactor
        self._env_allowlist = env_allowlist
        self._timeout = timeout
        self._slots = asyncio.Semaphore(8)
        self._jobs: set[asyncio.Task[Any]] = set()

    def hosts(self) -> tuple[Host, ...]:
        """Return public identifiers and display names for configured hosts."""
        return tuple(Host(item.id, item.name or item.id) for item in self._hosts.values())

    async def _call[T](self, host: str, operation: Callable[[DockerAPI], T], sdk_timeout: float | None = None) -> T:
        """Run SDK work off-loop and retain its slot until the worker actually finishes."""
        config = self._hosts.get(host)
        if config is None:
            raise DockSightError("host_not_found", "Configured host not found", 404)
        effective_timeout = self._timeout if sdk_timeout is None else min(sdk_timeout, self._timeout)

        def run() -> T:
            """Close the SDK client and translate transport failures into domain errors."""
            try:
                client = connect(config, effective_timeout)
                try:
                    return operation(cast(DockerAPI, client.api))
                finally:
                    client.close()
            except NotFound as exc:
                raise DockSightError("container_not_found", "Container not found", 404) from exc
            except (DockerException, RequestException, SSHException, OSError) as exc:
                raise DockSightError("runtime_unavailable", "Docker operation failed", 503) from exc

        try:
            async with asyncio.timeout(effective_timeout + 5):
                await self._slots.acquire()
                task = asyncio.create_task(asyncio.to_thread(run))
                self._jobs.add(task)

                def finished(job: asyncio.Task[T]) -> None:
                    """Release the worker slot and consume background task failures."""
                    self._jobs.discard(job)
                    self._slots.release()
                    if not job.cancelled():
                        job.exception()

                task.add_done_callback(finished)

                return await asyncio.shield(task)
        except TimeoutError as exc:
            raise DockSightError("runtime_timeout", "Docker operation timed out", 504) from exc

    async def ping(self, host: str) -> None:
        """Use a short SDK timeout while preserving worker-slot ownership after cancellation."""
        if not await self._call(host, lambda client: client.ping(), sdk_timeout=3):
            raise DockSightError("runtime_unavailable", "Docker ping failed", 503)

    async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
        """Read and sanitize at most 200 container snapshots."""

        def read(client: DockerAPI) -> tuple[ContainerSnapshot, ...]:
            """Inspect listed containers using the same host connection."""
            return tuple(
                map_container(client.inspect_container(row["Id"]), host, self._env_allowlist, self._redactor)
                for row in client.containers(all=True, limit=200)
            )

        return await self._call(host, read)

    async def inspect(self, host: str, container_id: str) -> ContainerSnapshot:
        """Read one allowlisted and sanitized inspect snapshot."""
        return await self._call(
            host,
            lambda client: map_container(
                client.inspect_container(container_id),
                host,
                self._env_allowlist,
                self._redactor,
            ),
        )

    async def logs(self, host: str, container_id: str, lines: int, max_bytes: int) -> LogBatch:
        """Read finite logs with container-specific secret redaction."""

        def read(client: DockerAPI) -> LogBatch:
            """Consume a finite Docker tail within a hard scan limit, then sanitize before clipping output."""
            raw = client.inspect_container(container_id)
            config: dict[str, Any] = raw.get("Config") or {}
            environment: list[str] = config.get("Env") or []
            redactor = self._redactor.with_environment(environment)
            stream = client.logs(container_id, tail=lines, timestamps=True, stream=True, follow=False)
            chunks = bytearray()
            with closing(stream):
                for chunk in stream:
                    if len(chunks) + len(chunk) > MAX_LOG_SCAN_BYTES:
                        raise DockSightError(
                            "log_read_limit",
                            "Docker log tail exceeded the bounded read limit; latest output is unknown",
                            502,
                        )
                    chunks.extend(chunk)

            return parse_logs(bytes(chunks), redactor, max_bytes, lines)

        return await self._call(host, read)

    async def stats(self, host: str, container_id: str) -> ResourceMetrics:
        """Read resource metrics only when the container is running."""

        def read(client: DockerAPI) -> ResourceMetrics:
            """Skip stopped containers before requesting Docker counter deltas."""
            raw = client.inspect_container(container_id)
            if raw["State"]["Status"] != "running":
                return ResourceMetrics()

            return map_metrics(client.stats(container_id, stream=False))

        return await self._call(host, read)

    async def stacks(self, host: str, kind: Literal["compose", "swarm"]) -> tuple[StackSummary, ...]:
        """Read Compose groups or manager-only Swarm service summaries."""
        if kind == "compose":
            return compose_stacks(await self.containers(host))
        return await self._call(host, lambda client: swarm_stacks(client, self._redactor))

    async def restart(self, host: str, container_id: str) -> None:
        """Restart an exact container without retrying the mutation."""
        await self._call(host, lambda client: client.restart(container_id, timeout=10))

    async def stop(self, host: str, container_id: str) -> None:
        """Stop an exact container without retrying the mutation."""
        await self._call(host, lambda client: client.stop(container_id, timeout=10))

    async def close(self) -> None:
        """Wait for outstanding SDK workers before application shutdown."""
        if self._jobs:
            await asyncio.gather(*self._jobs, return_exceptions=True)
