from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from importlib import metadata
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from docksight.adapters.inbound.http.auth import AuthenticationError, HttpAuthentication
from docksight.adapters.inbound.http.auth_routes import build_auth_router
from docksight.adapters.inbound.http.errors import error_response, install_errors, status_code
from docksight.adapters.inbound.http.investigations import build_investigations_router
from docksight.adapters.inbound.http.middleware import BodyLimit
from docksight.adapters.inbound.http.routes import build_router
from docksight.bootstrap import Components, Settings, build_components
from docksight.domain.errors import DockSightError


def create_app(settings: Settings | None = None, components: Components | None = None) -> FastAPI:
    """Create the HTTP application with explicit service ownership and safe defaults."""
    config = settings or Settings()
    services = components or build_components(config)
    auth = HttpAuthentication(
        services.browser_sessions,
        config.api_credentials(),
        browser_origin=config.browser_origin,
        cors_origins=config.cors_origins,
        cookie_secure=config.cookie_secure,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Close application services after the server stops accepting work."""
        try:
            await services.start()
            yield
        finally:
            await services.close()

    version = metadata.version("docksight")
    app = FastAPI(title="DockSight", version=version, lifespan=lifespan)
    app.add_middleware(BodyLimit)
    install_errors(app)
    app.include_router(
        build_router(
            services.queries,
            services.actions,
            services.status,
            services.investigations,
            services.runner,
            auth,
            services.models,
        )
    )
    app.include_router(build_investigations_router(services.investigations, services.runner, auth))
    app.include_router(build_auth_router(auth))

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Assign request IDs and enforce API authentication before dispatch."""
        request_id = str(uuid4())
        request.state.request_id = request_id
        denial = await _authorize(request, auth)
        if denial is not None:
            return denial
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"

        return response

    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.cors_origins),
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-CSRF-Token"],
            expose_headers=["X-Request-ID"],
        )

    @app.get("/health/live", tags=["Health"])
    async def live() -> dict[str, str]:
        """Report process liveness without contacting Docker or a model provider."""
        return {"status": "ok", "version": version}

    @app.get("/health/ready", tags=["Health"], response_model=None)
    async def ready() -> dict[str, str] | Response:
        """Report that application configuration and service wiring succeeded."""
        return _readiness(services)

    return app


def _readiness(services: Components) -> dict[str, str] | Response:
    """Report readiness only after startup recovery and while storage admits durable work."""
    if not services.ready or (services.database is not None and not services.database.healthy):
        return Response(status_code=503)
    return {"status": "ready"}


async def _authorize(request: Request, auth: HttpAuthentication) -> Response | None:
    """Resolve shared API authority before dispatch and normalize safe middleware failures."""
    if not request.url.path.startswith("/api/"):
        return None
    try:
        await auth.resolve(request)
    except AuthenticationError as error:
        response = error_response(request, error.code, error.message, error.status)
        if error.status == 401:
            response.headers["WWW-Authenticate"] = "Bearer"
        return response
    except DockSightError as error:
        return error_response(request, error.code, error.message, status_code(error.kind))
    return None
