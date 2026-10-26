from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from hmac import compare_digest
from importlib import metadata
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from docksight.adapters.inbound.http.errors import error_response, install_errors
from docksight.adapters.inbound.http.middleware import BodyLimit
from docksight.adapters.inbound.http.routes import build_router
from docksight.bootstrap import Components, Settings, build_components


def create_app(settings: Settings | None = None, components: Components | None = None) -> FastAPI:
    """Create the HTTP application with explicit service ownership and safe defaults."""
    config = settings or Settings()
    services = components or build_components(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Close application services after the server stops accepting work."""
        try:
            yield
        finally:
            await services.close()

    version = metadata.version("docksight")
    app = FastAPI(title="DockSight", version=version, lifespan=lifespan)
    app.add_middleware(BodyLimit)
    install_errors(app)
    app.include_router(build_router(services.queries, services.diagnostics, services.actions))

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Assign request IDs and enforce API authentication before dispatch."""
        request_id = str(uuid4())
        request.state.request_id = request_id
        denial = _authorize(request, config)
        if denial is not None:
            return denial
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        return response

    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
            expose_headers=["X-Request-ID"],
        )

    @app.get("/health/live", tags=["Health"])
    async def live() -> dict[str, str]:
        """Report process liveness without contacting Docker or a model provider."""
        return {"status": "ok", "version": version}

    @app.get("/health/ready", tags=["Health"])
    async def ready() -> dict[str, str]:
        """Report that application configuration and service wiring succeeded."""
        return {"status": "ready"}

    return app


def _authorize(request: Request, config: Settings) -> Response | None:
    """Authenticate API requests and reject origins outside the configured allowlist."""
    if not request.url.path.startswith("/api/"):
        return None
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not compare_digest(token.encode(), config.api_token.get_secret_value().encode()):
        response = error_response(request, "unauthorized", "Authentication required", 401)
        response.headers["WWW-Authenticate"] = "Bearer"

        return response
    origin = request.headers.get("origin")
    same_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin and origin != same_origin and origin not in config.cors_origins:
        return error_response(request, "origin_not_allowed", "Origin is not allowed", 403)
    return None
