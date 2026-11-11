import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from docksight.adapters.inbound.http.legacy import legacy_events
from docksight.adapters.inbound.http.streaming import EventResponse, encode_events
from docksight.application.diagnostics.use_case import Diagnostics
from docksight.application.investigations.contracts import SavedTurn
from docksight.application.investigations.errors import StorageError
from docksight.application.ports.models import ModelReply, ToolCall
from docksight.application.redaction import Redactor
from docksight.domain.diagnostics import JsonObject
from tests.diagnostics import diagnostic_stream
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


async def test_expected_storage_failure_retains_public_code_without_an_unsaved_answer() -> None:
    async def source():
        """Fail observation because no next committed snapshot can be read."""
        yield {"type": "turn.started", "turn_id": "t1", "session_id": "i1"}
        raise StorageError()

    chunks = [chunk async for chunk in encode_events(source(), "original-request")]
    events = [json.loads(line[6:]) for chunk in chunks for line in chunk.splitlines() if line.startswith("data: ")]
    assert events[-1]["code"] == "storage_unavailable"
    assert events[-1]["request_id"] == "original-request"
    assert all(event["type"] != "answer.ready" for event in events)


async def test_legacy_response_closes_registered_observer_before_first_body_iteration() -> None:
    closed = asyncio.Event()
    initial = SavedTurn(
        id=str(uuid4()),
        investigation_id=str(uuid4()),
        actor="operator",
        host="local",
        submission_id=str(uuid4()),
        request_id="original",
        query="Inspect",
        state="running",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    async def source():
        """Represent an observer that was already registered before response headers were sent."""
        try:
            yield initial
            await asyncio.Event().wait()
        finally:
            closed.set()

    async def send(message):
        """Simulate an HTTP disconnect before Starlette asks for the first body chunk."""
        raise asyncio.CancelledError()

    async def receive():
        """Keep the ASGI receive contract available for a modern disconnect-aware response."""
        return {"type": "http.disconnect"}

    observer = source()
    assert await anext(observer) == initial
    response = EventResponse(legacy_events(observer, initial), "original", observer=observer)
    with pytest.raises(asyncio.CancelledError):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    assert closed.is_set()


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

    service = Diagnostics(SlowRuntime(), SlowModel(), Redactor(), timeout=0.02)
    encoded = encode_events(diagnostic_stream(service, "operator", "local", "Inspect worker"), "r1", heartbeat=0.005)
    async with asyncio.timeout(0.5):
        chunks = [chunk async for chunk in encoded]
    events = [json.loads(line[6:]) for chunk in chunks for line in chunk.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "turn.failed"
    assert events[-1]["code"] == "turn_timeout"
    assert sum(event["type"] == "turn.failed" for event in events) == 1
    step = events[-2]["step"]
    assert step["state"] == "failed"
    assert step["code"] == "turn_timeout"
    assert step["duration_ms"] >= 0
    lease = await service.reserve()
    await lease.close()
