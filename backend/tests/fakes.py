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
