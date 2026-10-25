import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import suppress

import anyio
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from docksight.adapters.inbound.http.errors import safe_stack
from docksight.application.events import TurnEvent


async def encode_events(
    source: AsyncGenerator[TurnEvent],
    request_id: str,
    heartbeat: float = 10,
) -> AsyncGenerator[str]:
    pending: asyncio.Task[TurnEvent] | None = asyncio.create_task(anext(source))
    turn_id: str | None = None
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=heartbeat)
            if not done:
                yield ": heartbeat\n\n"
                continue
            job, pending = pending, None
            try:
                event = job.result()
            except StopAsyncIteration:
                return
            kind = str(event["type"])
            turn_id = str(event.get("turn_id", ""))
            data = {**event, "schema_version": 1, "request_id": request_id}
            yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            if kind in {"turn.completed", "turn.failed"}:
                return
            pending = asyncio.create_task(anext(source))
    except Exception as exc:
        logging.getLogger("docksight.http").error(
            json.dumps(
                {
                    "event": "stream.failed",
                    "request_id": request_id,
                    "error_type": type(exc).__name__,
                    "stack": safe_stack(exc),
                }
            )
        )
        data = {
            "type": "turn.failed",
            "turn_id": turn_id,
            "schema_version": 1,
            "request_id": request_id,
            "code": "internal_error",
            "message": "Diagnostic processing failed",
        }
        yield f"event: turn.failed\ndata: {json.dumps(data)}\n\n"
    finally:
        if pending is not None:
            pending.cancel()
            with suppress(asyncio.CancelledError, StopAsyncIteration):
                await pending
        await source.aclose()


class EventResponse(StreamingResponse):
    def __init__(
        self, source: AsyncGenerator[TurnEvent], request_id: str, status_code: int = 200
    ) -> None:
        self.events = encode_events(source, request_id)
        super().__init__(
            self.events,
            media_type="text/event-stream",
            status_code=status_code,
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self.events.aclose()
