from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

from docksight.application.ports.models import ModelMessage, ModelReply, ToolSpec
from docksight.domain.diagnostics import JsonObject
from docksight.domain.runtime import (
    ContainerSnapshot,
    Host,
    LogBatch,
    LogEntry,
    ResourceMetrics,
    StackMember,
    StackSummary,
)


def snapshot(state: str = "exited") -> ContainerSnapshot:
    """Build a deterministic exact-container snapshot for runtime tests."""
    return ContainerSnapshot(
        "local",
        "a" * 64,
        "worker",
        "worker:1",
        state,
        1,
        False,
        0,
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime.now(UTC),
    )


class FakeRuntime:
    """Provide deterministic runtime snapshots while recording requested mutations."""

    def __init__(self) -> None:
        """Start with one failed worker and a fixed sanitized log batch."""
        self.item = snapshot()
        self.mutations: list[str] = []
        self.log_batch = LogBatch((LogEntry("ConnectionRefusedError: database unavailable"),))

    def hosts(self) -> tuple[Host, ...]:
        """Return the configured public host inventory."""
        return (Host("local", "Local"),)

    async def ping(self, host: str) -> None:
        """Report an available fake engine without reading or changing its workloads."""

    async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
        """Read bounded sanitized container snapshots for one host."""
        return (self.item,)

    async def inspect(self, host: str, container_id: str) -> ContainerSnapshot:
        """Read one sanitized container snapshot on the selected host."""
        return self.item

    async def logs(self, host: str, container_id: str, lines: int, max_bytes: int) -> LogBatch:
        """Read sanitized container logs within explicit line and byte limits."""
        return self.log_batch

    async def stats(self, host: str, container_id: str) -> ResourceMetrics:
        """Read current container metrics and retain missing values as unavailable."""
        return ResourceMetrics(None, 1024, 4096)

    async def stacks(self, host: str, kind: str) -> tuple[StackSummary, ...]:
        """Read Compose grouping or manager-only Swarm service summaries."""
        return (StackSummary("demo", "compose", 1, 0, (self.item.id,)),)

    async def restart(self, host: str, container_id: str) -> None:
        """Restart the exact container selected by a validated action."""
        self.mutations.append("restart")
        self.item = replace(self.item, state="running", started_at=datetime.now(UTC))

    async def stop(self, host: str, container_id: str) -> None:
        """Stop the exact container selected by a validated action."""
        self.mutations.append("stop")
        self.item = replace(self.item, state="exited", started_at=datetime.now(UTC))


class DiscoveryRuntime(FakeRuntime):
    """Expose two project failures and an unrelated failed container for scope-selection tests."""

    def __init__(self) -> None:
        """Keep independent identities and record reads before any diagnostic explanation."""
        super().__init__()
        self.rows = (
            replace(self.item, id="1" * 64, name="backend-1", compose_project="vintoria-infra"),
            replace(self.item, id="2" * 64, name="grafana-1", compose_project="vintoria-infra"),
            replace(self.item, id="3" * 64, name="unrelated-1", compose_project="other-project"),
        )
        self.reads: list[str] = []

    async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
        """Return the observed names that the agent may select."""
        return self.rows

    async def inspect(self, host: str, container_id: str) -> ContainerSnapshot:
        """Resolve only exact fixture identities."""
        return next(row for row in self.rows if row.id == container_id)

    async def logs(self, host: str, container_id: str, lines: int, max_bytes: int) -> LogBatch:
        """Record log scope so unrelated collection cannot pass unnoticed."""
        self.reads.append(container_id)
        return self.log_batch

    async def stacks(self, host: str, kind: str) -> tuple[StackSummary, ...]:
        """Derive actual Compose membership without exposing a fictional Swarm stack."""
        if kind == "swarm":
            return ()
        return tuple(
            StackSummary(
                name,
                "compose",
                len(rows),
                0,
                tuple(row.id for row in rows),
                tuple(StackMember(row.id, row.name, "container", row.state, 1, 0, row.exit_code) for row in rows),
            )
            for name in ("vintoria-infra", "other-project")
            if (rows := tuple(row for row in self.rows if row.compose_project == name))
        )


class ScriptedModel:
    """Return scripted replies and retain model requests for assertions."""

    def __init__(self, replies: list[ModelReply]) -> None:
        """Store queued replies and initialize the captured request list."""
        self.replies = replies
        self.requests: list[tuple[list[ModelMessage], bool]] = []

    async def complete(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec] = (),
        schema: JsonObject | None = None,
    ) -> ModelReply:
        """Capture the requested schema mode and consume the next scripted reply."""
        self.requests.append((list(messages), schema is not None))
        return self.replies.pop(0)


class FakeAudit:
    """Capture emitted audit event names without external output."""

    def __init__(self) -> None:
        """Initialize the recorded audit event list."""
        self.events: list[str] = []

    async def record(self, event: str, data: JsonObject) -> None:
        """Append an audit event for test assertions."""
        self.events.append(event)
