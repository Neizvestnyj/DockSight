import asyncio
import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep

from docksight.application.ports.models import ModelMessage, ModelReply, ToolSpec
from docksight.domain.diagnostics import JsonObject
from docksight.domain.runtime import ContainerSnapshot, StackSummary
from tests.fakes import FakeRuntime


def record(directory: Path, event: str, **data: str | int) -> None:
    """Append content-free test correlation without headers, prompts, or model payloads."""
    with (directory / "events.jsonl").open("a", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps({"event": event, **data}) + "\n")


async def barrier(directory: Path, name: str) -> None:
    """Expose a file marker and await explicit release within a bounded test window."""
    if not (directory / f"{name}.block").exists():
        return
    (directory / f"{name}.entered").touch()
    await asyncio.to_thread(wait_until, lambda: not (directory / f"{name}.block").exists(), 120)


def wait_until(predicate: Callable[[], bool], timeout: float) -> None:
    """Wait on cross-process file state outside the event loop with a hard fixture deadline."""
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.02)
    raise TimeoutError("Owned fixture barrier did not settle")


class PersistentRuntime(FakeRuntime):
    """Serve exact deterministic identities and process-visible mutation barriers."""

    def __init__(self, directory: Path) -> None:
        """Bind all counters and barriers to the owning test directory."""
        super().__init__()
        self.directory = directory
        self.peer = replace(self.item, id="b" * 64, name="other-project", compose_project="other-project")

    async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
        """Expose one worker and a deliberate container/project clarification candidate."""
        return self.item, self.peer

    async def inspect(self, host: str, container_id: str) -> ContainerSnapshot:
        """Resolve exact fixture IDs and record fresh evidence collection."""
        record(self.directory, "runtime.inspect", container_id=container_id)
        return self.peer if container_id == self.peer.id else self.item

    async def stacks(self, host: str, kind: str) -> tuple[StackSummary, ...]:
        """Derive the peer's real fixture membership for deterministic ambiguity."""
        return (StackSummary("other-project", "compose", 1, 0, (self.peer.id,)),) if kind == "compose" else ()

    async def restart(self, host: str, container_id: str) -> None:
        """Pause after the committed dispatch marker before recording one fake mutation."""
        await barrier(self.directory, "mutation")
        record(self.directory, "runtime.restart", container_id=container_id)
        await super().restart(host, container_id)

    async def stop(self, host: str, container_id: str) -> None:
        """Pause an explicitly confirmed stop using the same owned dispatch barrier."""
        await barrier(self.directory, "mutation")
        record(self.directory, "runtime.stop", container_id=container_id)
        await super().stop(host, container_id)


class PersistentModel:
    """Count exploration and finalization independently without persisting model input."""

    def __init__(self, directory: Path) -> None:
        """Retain only the test-owned IPC directory."""
        self.directory = directory

    async def complete(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolSpec] = (),
        schema: JsonObject | None = None,
    ) -> ModelReply:
        """Return deterministic valid text after an explicitly released file barrier."""
        record(self.directory, "model.final" if schema is not None else "model.exploration")
        await barrier(self.directory, "model")
        return ModelReply(
            '{"summary":"Retained worker answer","uncertain":true,"evidence_ids":[],"widgets":[]}'
            if schema is not None
            else "Ready"
        )
