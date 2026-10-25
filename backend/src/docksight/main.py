from collections.abc import Awaitable, Callable
from hmac import compare_digest
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from docksight.bootstrap import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    app = FastAPI(title="DockSight", version="0.1.0")
    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        )

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = str(uuid4())
        request.state.request_id = request_id
        if request.url.path.startswith("/api/"):
            authorization = request.headers.get("authorization", "")
            expected = f"Bearer {config.api_token.get_secret_value()}"
            if not compare_digest(authorization.encode(), expected.encode()):
                return JSONResponse(
                    status_code=401,
                    content={"code": "unauthorized", "message": "Authentication required"},
                    headers={"WWW-Authenticate": "Bearer", "X-Request-ID": request_id},
                )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        return response

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/health/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready"}

    return app
