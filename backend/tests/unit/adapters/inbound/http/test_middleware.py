import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException
from starlette.types import Message, Receive, Scope, Send

from docksight.adapters.inbound.http.errors import install_errors
from docksight.adapters.inbound.http.middleware import BodyLimit


async def test_body_limit_does_not_send_a_second_response_after_start() -> None:
    sent: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        """Start a response before requesting an oversized input chunk."""
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()

    async def receive() -> Message:
        """Return an input chunk exceeding the middleware limit."""
        return {"type": "http.request", "body": b"x" * 20000, "more_body": True}

    async def send(message: Message) -> None:
        """Capture every outgoing ASGI message for protocol validation."""
        sent.append(message)

    with pytest.raises(HTTPException) as error:
        await BodyLimit(app)({"type": "http", "headers": []}, receive, send)
    assert error.value.status_code == 413
    assert [message["type"] for message in sent] == ["http.response.start"]


def test_http_errors_preserve_authentication_headers_without_request_context() -> None:
    app = FastAPI()
    install_errors(app)

    @app.get("/protected")
    async def protected() -> None:
        """Return an HTTP challenge from a downstream dependency."""
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})

    with TestClient(app) as client:
        response = client.get("/protected")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"code": "http_error", "message": "Authentication required"}
