import asyncio
from collections.abc import AsyncGenerator

from docksight.adapters.inbound.http.streaming import encode_events
from docksight.domain.diagnostics import JsonObject


async def test_unexpected_source_failure_emits_one_safe_terminal_event() -> None:
    async def source() -> AsyncGenerator[JsonObject]:
        yield {"type": "turn.started", "turn_id": "t1"}
        raise RuntimeError("private-sentinel")

    chunks = [chunk async for chunk in encode_events(source(), "r1")]
    text = "".join(chunks)
    assert text.count("event: turn.failed") == 1
    assert "private-sentinel" not in text


async def test_closing_heartbeat_stream_cancels_pending_work() -> None:
    closed = asyncio.Event()

    async def source() -> AsyncGenerator[JsonObject]:
        try:
            await asyncio.sleep(20)
            yield {"type": "turn.completed"}
        finally:
            closed.set()

    encoded = encode_events(source(), "r1", heartbeat=0.001)
    assert await anext(encoded) == ": heartbeat\n\n"
    await encoded.aclose()
    assert closed.is_set()
