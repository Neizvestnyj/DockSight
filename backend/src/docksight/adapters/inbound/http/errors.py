import json
import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from docksight.domain.errors import DockSightError


def safe_stack(exc: Exception) -> list[dict[str, str | int]]:
    return [
        {"file": frame.filename, "line": frame.lineno or 0, "function": frame.name}
        for frame in traceback.extract_tb(exc.__traceback__)
    ]


def error_response(request: Request, code: str, message: str, status: int) -> JSONResponse:
    request_id: str = request.state.request_id

    return JSONResponse(
        {"code": code, "message": message, "request_id": request_id},
        status_code=status,
        headers={"X-Request-ID": request_id},
    )


def install_errors(app: FastAPI) -> None:
    @app.exception_handler(DockSightError)
    async def domain_error(request: Request, exc: DockSightError) -> JSONResponse:
        return error_response(request, exc.code, exc.message, exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            request, "invalid_request", "Request does not match the API schema", 422
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
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
