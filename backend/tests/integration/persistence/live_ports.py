from collections.abc import Sequence
from pathlib import Path

from docksight.adapters.outbound.docker.hosts import load_hosts
from docksight.adapters.outbound.docker.runtime import DockerRuntime
from docksight.application.ports.models import ModelMessage, ModelPort, ModelReply, ToolSpec
from docksight.application.redaction import Redactor
from docksight.domain.diagnostics import JsonObject
from docksight.domain.runtime import ContainerSnapshot, Host, LogBatch, ResourceMetrics, StackSummary
from tests.integration.persistence.ports import barrier, record


class ScopedDocker:
    """Delegate real Docker operations only for the fixture's exact owned resource."""

    def __init__(self, directory: Path, container_id: str) -> None:
        """Configure a bounded production runtime without permitting unscoped inventory reads."""
        self.directory = directory
        self.container_id = container_id
        self.runtime = DockerRuntime(load_hosts(None), Redactor(), timeout=15)

    def require(self, host: str, container_id: str) -> None:
        """Reject every host or identity outside the explicitly allocated fixture."""
        if host != "local" or container_id != self.container_id:
            raise AssertionError("Runtime access is outside the owned Docker fixture")

    def hosts(self) -> tuple[Host, ...]:
        """Expose a neutral fixture label instead of private host information."""
        return (Host("local", "Fixture Docker"),)

    async def ping(self, host: str) -> None:
        """Check the approved local engine without reading container inventory."""
        self.require(host, self.container_id)
        await self.runtime.ping(host)

    async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
        """Construct inventory by inspecting only this fixture's full resource ID."""
        return (await self.inspect(host, self.container_id),)

    async def inspect(self, host: str, container_id: str) -> ContainerSnapshot:
        """Collect sanitized fresh state only from the exact owned container."""
        self.require(host, container_id)
        record(self.directory, "runtime.inspect", container_id=container_id)
        return await self.runtime.inspect(host, container_id)

    async def logs(self, host: str, container_id: str, lines: int, max_bytes: int) -> LogBatch:
        """Collect only the fixture program's bounded public test messages."""
        self.require(host, container_id)
        record(self.directory, "runtime.logs", container_id=container_id)
        return await self.runtime.logs(host, container_id, min(lines, 10), min(max_bytes, 4096))

    async def stats(self, host: str, container_id: str) -> ResourceMetrics:
        """Read metrics for the owned fixture without querying unrelated workloads."""
        self.require(host, container_id)
        return await self.runtime.stats(host, container_id)

    async def stacks(self, host: str, kind: str) -> tuple[StackSummary, ...]:
        """Keep the deliberately ungrouped fixture separate from user Compose and Swarm resources."""
        self.require(host, self.container_id)
        return ()

    async def restart(self, host: str, container_id: str) -> None:
        """Send exactly one real restart, then expose a controlled pre-terminal crash window."""
        self.require(host, container_id)
        await self.runtime.restart(host, container_id)
        record(self.directory, "runtime.restart", container_id=container_id)
        await barrier(self.directory, "mutation")

    async def stop(self, host: str, container_id: str) -> None:
        """Send exactly one real stop only after server confirmation and identity validation."""
        self.require(host, container_id)
        await self.runtime.stop(host, container_id)
        record(self.directory, "runtime.stop", container_id=container_id)
        await barrier(self.directory, "mutation")

    async def close(self) -> None:
        """Drain only SDK work owned by this wrapper."""
        await self.runtime.close()


class CountedModel:
    """Observe natural local-provider calls without saving messages, reasoning, or provider payloads."""

    def __init__(self, directory: Path, delegate: ModelPort) -> None:
        """Bind one approved local provider through its production model adapter."""
        self.directory = directory
        self.delegate = delegate

    async def complete(
        self, messages: Sequence[ModelMessage], tools: Sequence[ToolSpec] = (), schema: JsonObject | None = None
    ) -> ModelReply:
        """Pause deterministically before a real provider call and count completion separately."""
        kind = "final" if schema is not None else "exploration"
        record(self.directory, f"model.{kind}", context_messages=len(messages))
        await barrier(self.directory, "model")
        reply = await self.delegate.complete(messages, tools, schema)
        record(self.directory, f"model.{kind}.done")
        return reply
