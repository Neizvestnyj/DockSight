import asyncio
import json
from collections.abc import AsyncGenerator

import pytest

from docksight.adapters.inbound.http.streaming import encode_events
from docksight.adapters.outbound.memory.sessions import MemorySessions
from docksight.application.diagnostics.use_case import Diagnostics
from docksight.application.ports.models import ModelReply, ToolCall
from docksight.application.redaction import Redactor
from docksight.domain.diagnostics import JsonObject
from tests.fakes import FakeRuntime


async def test_unexpected_source_failure_emits_one_safe_terminal_event() -> None:

    async def source() -> AsyncGenerator[JsonObject]:
        """Yield controlled events to exercise stream failure or cancellation cleanup."""
        yield {"type": "turn.started", "turn_id": "t1"}
        raise RuntimeError("private-sentinel")

    chunks = [chunk async for chunk in encode_events(source(), "r1")]
    text = "".join(chunks)
    assert text.count("event: turn.failed") == 1
    assert "private-sentinel" not in text


async def test_closing_heartbeat_stream_cancels_pending_work() -> None:
    closed = asyncio.Event()

    async def source() -> AsyncGenerator[JsonObject]:
        """Yield controlled events to exercise stream failure or cancellation cleanup."""
        try:
            await asyncio.sleep(20)
            yield {"type": "turn.completed"}
        finally:
            closed.set()

    encoded = encode_events(source(), "r1", heartbeat=0.001)
    assert await anext(encoded) == ": heartbeat\n\n"
    await encoded.aclose()
    assert closed.is_set()


@pytest.mark.parametrize("stage", ["model", "tool", "final"])
async def test_turn_deadline_survives_sse_task_boundaries(stage: str) -> None:

    class SlowRuntime(FakeRuntime):
        """Delay runtime reads or mutations to exercise timeout handling."""

        async def inspect(self, host: str, container_id: str):
            """Delay the inspect call before returning the configured snapshot."""
            if stage == "tool":
                await asyncio.Event().wait()
            return await super().inspect(host, container_id)

    class SlowModel:
        """Delay one model stage to exercise the turn's absolute deadline."""

        async def complete(self, messages, tools=(), schema=None):
            """Delay the selected stage and return the scripted model reply."""
            if stage == "model" or schema is not None:
                await asyncio.Event().wait()
            if stage == "tool":
                return ModelReply("", (ToolCall("c1", "inspect_container", {"container_id": "worker"}),))
            return ModelReply("Ready")

    sessions = MemorySessions()
    service = Diagnostics(SlowRuntime(), SlowModel(), sessions, Redactor(), timeout=0.02)
    encoded = encode_events(service.stream("operator", "local", "Inspect worker"), "r1", heartbeat=0.005)
    async with asyncio.timeout(0.5):
        chunks = [chunk async for chunk in encoded]
    events = [json.loads(line[6:]) for chunk in chunks for line in chunk.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "turn.failed"
    assert events[-1]["code"] == "turn_timeout"
    assert sum(event["type"] == "turn.failed" for event in events) == 1
    async with sessions.lease(events[0]["session_id"], "operator", "local"):
        pass
