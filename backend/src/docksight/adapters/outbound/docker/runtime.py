import asyncio
from collections.abc import Callable, Iterator
from contextlib import closing
from typing import Any, Literal, Protocol, cast

from docker.errors import DockerException, NotFound
from paramiko import SSHException
from requests import RequestException

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


class LogStream(Protocol):
    def __iter__(self) -> Iterator[bytes]: ...
    def close(self) -> None: ...


class DockerAPI(Protocol):
    """Describe the low-level SDK surface whose upstream stubs are incomplete."""

    def inspect_container(self, container: str) -> dict[str, Any]: ...
    def containers(self, *, all: bool, limit: int) -> list[dict[str, Any]]: ...
    def logs(
        self, container: str, *, tail: int, timestamps: bool, stream: bool, follow: bool
    ) -> LogStream: ...
    def stats(self, container: str, *, stream: bool) -> dict[str, Any]: ...
    def info(self) -> dict[str, Any]: ...
    def services(self) -> list[dict[str, Any]]: ...
    def tasks(self, *, filters: dict[str, str]) -> list[dict[str, Any]]: ...
    def restart(self, container: str, *, timeout: int) -> None: ...
    def stop(self, container: str, *, timeout: int) -> None: ...


class DockerRuntime:
    def __init__(
        self,
        hosts: tuple[HostConfig, ...],
        redactor: Redactor,
        env_allowlist: tuple[str, ...] = (),
        timeout: float = 15,
    ) -> None:
        self._hosts = {host.id: host for host in hosts}
        self._redactor = redactor
        self._env_allowlist = env_allowlist
        self._timeout = timeout
        self._slots = asyncio.Semaphore(8)
        self._jobs: set[asyncio.Task[Any]] = set()

    def hosts(self) -> tuple[Host, ...]:
        return tuple(Host(item.id, item.name or item.id) for item in self._hosts.values())

    async def _call[T](self, host: str, operation: Callable[[DockerAPI], T]) -> T:
        config = self._hosts.get(host)
        if config is None:
            raise DockSightError("host_not_found", "Configured host not found", 404)

        def run() -> T:
            try:
                client = connect(config, self._timeout)
                try:
                    return operation(cast(DockerAPI, client.api))
                finally:
                    client.close()
            except NotFound as exc:
                raise DockSightError("container_not_found", "Container not found", 404) from exc
            except (DockerException, RequestException, SSHException, OSError) as exc:
                raise DockSightError("runtime_unavailable", "Docker operation failed", 503) from exc

        try:
            async with asyncio.timeout(self._timeout + 5):
                await self._slots.acquire()
                task = asyncio.create_task(asyncio.to_thread(run))
                self._jobs.add(task)

                def finished(job: asyncio.Task[T]) -> None:
                    self._jobs.discard(job)
                    self._slots.release()
                    if not job.cancelled():
                        job.exception()

                task.add_done_callback(finished)

                return await asyncio.shield(task)
        except TimeoutError as exc:
            raise DockSightError("runtime_timeout", "Docker operation timed out", 504) from exc

    async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
        def read(client: DockerAPI) -> tuple[ContainerSnapshot, ...]:
            return tuple(
                map_container(
                    client.inspect_container(row["Id"]), host, self._env_allowlist, self._redactor
                )
                for row in client.containers(all=True, limit=200)
            )

        return await self._call(host, read)

    async def inspect(self, host: str, container_id: str) -> ContainerSnapshot:
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
        def read(client: DockerAPI) -> LogBatch:
            raw = client.inspect_container(container_id)
            config: dict[str, Any] = raw.get("Config") or {}
            environment: list[str] = config.get("Env") or []
            redactor = self._redactor.with_environment(environment)
            stream = client.logs(
                container_id, tail=lines, timestamps=True, stream=True, follow=False
            )
            chunks = bytearray()
            with closing(stream):
                for chunk in stream:
                    chunks.extend(chunk[: max_bytes + 1 - len(chunks)])
                    if len(chunks) > max_bytes:
                        break

            return parse_logs(bytes(chunks), redactor, max_bytes, lines)

        return await self._call(host, read)

    async def stats(self, host: str, container_id: str) -> ResourceMetrics:
        def read(client: DockerAPI) -> ResourceMetrics:
            raw = client.inspect_container(container_id)
            if raw["State"]["Status"] != "running":
                return ResourceMetrics()

            return map_metrics(client.stats(container_id, stream=False))

        return await self._call(host, read)

    async def stacks(
        self, host: str, kind: Literal["compose", "swarm"]
    ) -> tuple[StackSummary, ...]:
        if kind == "compose":
            groups: dict[str, list[ContainerSnapshot]] = {}
            for item in await self.containers(host):
                if item.compose_project:
                    groups.setdefault(item.compose_project, []).append(item)

            return tuple(
                StackSummary(
                    name,
                    "compose",
                    len(rows),
                    sum(row.state == "running" for row in rows),
                    tuple(row.id for row in rows),
                )
                for name, rows in groups.items()
            )

        def read(client: DockerAPI) -> tuple[StackSummary, ...]:
            info: dict[str, Any] = client.info().get("Swarm") or {}
            if not info.get("ControlAvailable"):
                raise DockSightError("unsupported_operation", "Swarm reads require a manager", 409)
            summaries: list[StackSummary] = []
            for service in client.services():
                spec: dict[str, Any] = service["Spec"]
                mode: dict[str, Any] = spec.get("Mode") or {}
                replicated: dict[str, Any] = mode.get("Replicated") or {}
                tasks = client.tasks(filters={"service": service["ID"], "desired-state": "running"})
                total = replicated.get("Replicas", len(tasks))
                summaries.append(
                    StackSummary(
                        self._redactor.text(spec["Name"]),
                        "swarm",
                        total,
                        sum(task.get("Status", {}).get("State") == "running" for task in tasks),
                    )
                )

            return tuple(summaries)

        return await self._call(host, read)

    async def restart(self, host: str, container_id: str) -> None:
        await self._call(host, lambda client: client.restart(container_id, timeout=10))

    async def stop(self, host: str, container_id: str) -> None:
        await self._call(host, lambda client: client.stop(container_id, timeout=10))

    async def close(self) -> None:
        if self._jobs:
            await asyncio.gather(*self._jobs, return_exceptions=True)
