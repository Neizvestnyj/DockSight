from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from docksight.adapters.inbound.http.errors import error_response


class BodyLimit:
    """Bound HTTP request bodies, including requests without Content-Length."""

    def __init__(self, app: ASGIApp, limit: int = 16384) -> None:
        """Configure the maximum body size for the wrapped ASGI app."""
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Reject oversized declared or streamed HTTP request bodies."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = self.limit + 1
        if length > self.limit:
            await error_response(Request(scope), "request_too_large", "Request body exceeds 16 KiB", 413)(
                scope, receive, send
            )
            return
        received = 0

        async def bounded_receive() -> Message:
            """Count streamed body bytes before passing each message downstream."""
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    raise HTTPException(413, "Request body exceeds 16 KiB")

            return message

        await self.app(scope, bounded_receive, send)
