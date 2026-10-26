import json
import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from docksight.domain.errors import DockSightError


def safe_stack(exc: Exception) -> list[dict[str, str | int]]:
    """Return traceback locations without exception text or local values."""
    return [
        {"file": frame.filename, "line": frame.lineno or 0, "function": frame.name}
        for frame in traceback.extract_tb(exc.__traceback__)
    ]


def error_response(request: Request, code: str, message: str, status: int) -> JSONResponse:
    """Build a stable error envelope with its request identifier."""
    request_id: str | None = getattr(request.state, "request_id", None)
    body = {"code": code, "message": message}
    headers: dict[str, str] = {}
    if request_id is not None:
        body["request_id"] = request_id
        headers["X-Request-ID"] = request_id

    return JSONResponse(
        body,
        status_code=status,
        headers=headers,
    )


def install_errors(app: FastAPI) -> None:
    """Register safe handlers for domain, validation, and unexpected failures."""

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        """Normalize HTTP failures while preserving protocol-required response headers."""
        if exc.status_code == 413:
            response = error_response(request, "request_too_large", "Request body exceeds 16 KiB", 413)
        else:
            response = error_response(request, "http_error", str(exc.detail), exc.status_code)
        response.headers.update(exc.headers or {})
        return response

    @app.exception_handler(DockSightError)
    async def domain_error(request: Request, exc: DockSightError) -> JSONResponse:
        """Expose the domain error's public code, message, and status."""
        return error_response(request, exc.code, exc.message, exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Report invalid input without echoing submitted values."""
        return error_response(request, "invalid_request", "Request does not match the API schema", 422)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """Log safe traceback locations and return an opaque server error."""
        logging.getLogger("docksight.http").error(
            json.dumps(
                {
                    "event": "request.failed",
                    "request_id": request.state.request_id,
                    "error_type": type(exc).__name__,
                    "stack": safe_stack(exc),
                }
            )
        )

        return error_response(request, "internal_error", "Request processing failed", 500)
