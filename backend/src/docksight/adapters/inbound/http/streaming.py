import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import suppress
from typing import cast

import anyio
from fastapi import Request
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from docksight.adapters.inbound.http.auth import AuthenticationError, HttpAuthentication
from docksight.adapters.inbound.http.errors import safe_stack
from docksight.application.events import TurnEvent
from docksight.application.investigations.contracts import SavedTurn
from docksight.application.investigations.runner import TurnRunner
from docksight.domain.errors import DockSightError


async def encode_events(
    source: AsyncGenerator[TurnEvent],
    request_id: str,
    heartbeat: float = 10,
    auth: HttpAuthentication | None = None,
    request: Request | None = None,
) -> AsyncGenerator[str]:
    """Encode typed events with heartbeats and close pending work on disconnect."""
    pending: asyncio.Task[TurnEvent] | None = asyncio.create_task(anext(source))
    turn_id: str | None = None
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=heartbeat)
            await _authorize_stream(auth, request)
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
    except AuthenticationError:
        return
    except Exception as exc:
        yield _stream_failure(request_id, turn_id, exc)
    finally:
        await _cancel_next(pending)
        await source.aclose()


class EventResponse(StreamingResponse):
    """Serve diagnostic SSE and finalize its source during cancellation."""

    def __init__(
        self,
        source: AsyncGenerator[TurnEvent],
        request_id: str,
        status_code: int = 200,
        *,
        auth: HttpAuthentication | None = None,
        request: Request | None = None,
        observer: AsyncIterator[SavedTurn] | None = None,
    ) -> None:
        """Configure unbuffered event streaming and request metadata."""
        self.events = encode_events(source, request_id, auth=auth, request=request)
        self.observer = observer
        super().__init__(
            self.events,
            media_type="text/event-stream",
            status_code=status_code,
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Close the event generator even when ASGI cancels the response."""
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self.events.aclose()
                if self.observer is not None:
                    await _close_iterator(self.observer)


async def authorized_observation(
    runner: TurnRunner,
    actor: str,
    turn_id: str,
) -> tuple[AsyncGenerator[SavedTurn], SavedTurn]:
    """Register an owned observer before sending HTTP success or streaming headers."""
    source = runner.observe(actor, turn_id)
    try:
        initial = await anext(source)
    except BaseException:
        await source.aclose()
        raise
    return source, initial


async def encode_snapshots(
    source: AsyncIterator[SavedTurn],
    initial: SavedTurn,
    auth: HttpAuthentication,
    request: Request,
    actor: str,
    heartbeat: float = 10,
) -> AsyncGenerator[str]:
    """Publish committed snapshots while revalidating authority independently of retained work."""
    pending: asyncio.Task[SavedTurn] | None = None
    try:
        saved = initial
        await _revalidate_actor(auth, request, actor)
        yield _snapshot_frame(saved)
        if saved.state != "running":
            return
        pending = asyncio.create_task(_next_snapshot(source))
        while True:
            done, _ = await asyncio.wait({pending}, timeout=heartbeat)
            await _revalidate_actor(auth, request, actor)
            if not done:
                yield ": heartbeat\n\n"
                continue
            job, pending = pending, None
            saved = job.result()
            yield _snapshot_frame(saved)
            if saved.state != "running":
                return
            pending = asyncio.create_task(_next_snapshot(source))
    except (AuthenticationError, StopAsyncIteration):
        return
    except DockSightError as exc:
        data = {"schema_version": 1, "code": exc.code, "message": exc.message}
        yield f"event: error\ndata: {json.dumps(data)}\n\n"
    finally:
        await _cancel_next(pending)
        await _close_iterator(source)


class SnapshotResponse(StreamingResponse):
    """Own only a snapshot iterator and detach it on ASGI disconnect or session revocation."""

    def __init__(
        self,
        source: AsyncIterator[SavedTurn],
        initial: SavedTurn,
        auth: HttpAuthentication,
        request: Request,
        actor: str,
        status_code: int = 200,
    ) -> None:
        """Configure unbuffered versioned SSE without taking ownership of the diagnostic job."""
        self.snapshots = encode_snapshots(source, initial, auth, request, actor)
        self.source = source
        super().__init__(
            self.snapshots,
            media_type="text/event-stream",
            status_code=status_code,
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Finalize the observer even when the ASGI response task is cancelled."""
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self.snapshots.aclose()
                await _close_iterator(self.source)


async def _next_snapshot(source: AsyncIterator[SavedTurn]) -> SavedTurn:
    """Adapt any application snapshot iterator to an explicitly owned observer coroutine."""
    return await anext(source)


def _snapshot_frame(saved: SavedTurn) -> str:
    """Encode the stored originating request ID and committed revision without observer substitution."""
    return f"event: turn.snapshot\nid: {saved.revision}\ndata: {saved.model_dump_json()}\n\n"


async def _authorize_stream(auth: HttpAuthentication | None, request: Request | None) -> None:
    """Revalidate a stream's selected authority at updates and heartbeat boundaries."""
    if auth is not None and request is not None:
        await auth.resolve(request)


async def _cancel_next[T](pending: asyncio.Task[T] | None) -> None:
    """Cancel only the pending observer pull and retrieve its cancellation outcome."""
    if pending is not None:
        pending.cancel()
        with suppress(asyncio.CancelledError, StopAsyncIteration):
            await pending


async def _close_iterator[T](source: AsyncIterator[T]) -> None:
    """Release application observer registration when its iterator supports explicit closing."""
    if isinstance(source, AsyncGenerator):
        await cast(AsyncGenerator[T, None], source).aclose()


async def _revalidate_actor(auth: HttpAuthentication, request: Request, actor: str) -> None:
    """Reject changed, revoked, or expired authority before disclosing any saved revision."""
    if (await auth.resolve(request)).actor != actor:
        raise AuthenticationError()


def _stream_failure(request_id: str, turn_id: str | None, exc: Exception) -> str:
    """Preserve expected public failures and log safe traceback locations only for unexpected ones."""
    code, message = "internal_error", "Diagnostic processing failed"
    if isinstance(exc, DockSightError):
        code, message = exc.code, exc.message
    else:
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
        "code": code,
        "message": message,
    }
    return f"event: turn.failed\ndata: {json.dumps(data)}\n\n"
