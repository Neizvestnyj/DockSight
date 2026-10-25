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
    def __init__(self) -> None:
        self.item = snapshot()
        self.mutations: list[str] = []

    def hosts(self) -> tuple[Host, ...]:
        return (Host("local", "Local"),)

    async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
        return (self.item,)

    async def inspect(self, host: str, container_id: str) -> ContainerSnapshot:
        return self.item

    async def logs(self, host: str, container_id: str, lines: int, max_bytes: int) -> LogBatch:
        return LogBatch((LogEntry("ConnectionRefusedError: database unavailable"),))

    async def stats(self, host: str, container_id: str) -> ResourceMetrics:
        return ResourceMetrics(None, 1024, 4096)

    async def stacks(self, host: str, kind: str) -> tuple[StackSummary, ...]:
        return (StackSummary("demo", "compose", 1, 0, (self.item.id,)),)

    async def restart(self, host: str, container_id: str) -> None:
        self.mutations.append("restart")
        self.item = replace(self.item, state="running", started_at=datetime.now(UTC))

    async def stop(self, host: str, container_id: str) -> None:
        self.mutations.append("stop")
        self.item = replace(self.item, state="exited", started_at=datetime.now(UTC))


class ScriptedModel:
    def __init__(self, replies: list[ModelReply]) -> None:
        self.replies = replies
        self.requests: list[tuple[list[ModelMessage], bool]] = []

    async def complete(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec] = (),
        schema: JsonObject | None = None,
    ) -> ModelReply:
        self.requests.append((list(messages), schema is not None))
        return self.replies.pop(0)


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def record(self, event: str, data: JsonObject) -> None:
        self.events.append(event)
