import json
from typing import Final

import httpx
from pydantic import BaseModel, Field, ValidationError

from docksight.domain.errors import DockSightError, ErrorKind

MAX_BYTES: Final = 262144
MAX_MODELS: Final = 1900
MAX_PAGES: Final = 20


class _Row(BaseModel):
    """Read a bounded public model name and reliable modality metadata only."""

    id: str = Field(min_length=1, max_length=256)


class _Page(BaseModel):
    """Recognize provider pagination without retaining unrelated metadata."""

    data: list[_Row] = Field(max_length=2000)
    has_more: bool = False
    last_id: str | None = Field(default=None, max_length=256)


class _OllamaRow(BaseModel):
    """Read the native Ollama tag identity without guessing its chat capabilities."""

    name: str = Field(min_length=1, max_length=256)


class _Tags(BaseModel):
    """Bound native tag listings before publishing their public names."""

    models: list[_OllamaRow] = Field(max_length=MAX_MODELS)


class ModelCatalog:
    """Read bounded provider metadata using a reusable private HTTP connection."""

    def __init__(self, client: httpx.AsyncClient, provider: str) -> None:
        """Bind the configured endpoint and authentication independently of browser input."""
        self.client = client
        self.provider = provider

    async def fetch(self) -> tuple[str, ...]:
        """Follow bounded native pages and reject partial catalogs explicitly."""
        try:
            return await self._fetch()
        except httpx.TimeoutException as error:
            raise DockSightError("timeout", "Model catalog timed out", ErrorKind.DEPENDENCY) from error
        except httpx.HTTPError as error:
            raise DockSightError(
                "connection_failed", "Model catalog could not be reached", ErrorKind.DEPENDENCY
            ) from error
        except (ValidationError, ValueError) as error:
            raise DockSightError(
                "invalid_response", "Model catalog metadata is invalid", ErrorKind.DEPENDENCY
            ) from error

    async def _fetch(self) -> tuple[str, ...]:
        """Handle native endpoint formats and retain all pages within explicit global bounds."""
        if self.provider == "ollama":
            content = await self._read("api/tags", {})
            return tuple(row.name for row in _Tags.model_validate_json(content).models)
        path = _path(self.provider)
        rows: list[str] = []
        params: dict[str, str] = {}
        cursors: set[str] = set()
        for _ in range(MAX_PAGES):
            page = _Page.model_validate_json(await self._read(path, params))
            rows.extend(row.id for row in page.data)
            if len(rows) > MAX_MODELS:
                break
            if not page.has_more:
                return tuple(dict.fromkeys(rows))
            cursor = _next_cursor(page, cursors)
            cursors.add(cursor)
            params = _parameters(self.provider, cursor)
        raise DockSightError("partial_catalog", "Model catalog exceeded pagination limits", ErrorKind.DEPENDENCY)

    async def _read(self, path: str, params: dict[str, str]) -> bytes:
        """Bound decoded response memory and map status codes to safe public reasons."""
        async with self.client.stream("GET", path, params=params, timeout=5, follow_redirects=False) as response:
            if response.status_code != 200:
                codes = {
                    401: "credentials_rejected",
                    403: "metadata_forbidden",
                    404: "unsupported",
                    429: "rate_limited",
                }
                raise DockSightError(
                    codes.get(response.status_code, "upstream_error"), "Model catalog unavailable", ErrorKind.DEPENDENCY
                )
            content = bytearray()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > MAX_BYTES:
                    raise DockSightError(
                        "invalid_response", "Model catalog exceeded metadata limits", ErrorKind.DEPENDENCY
                    )
                content.extend(chunk)
        # Parse strictly here as JSON libraries otherwise accept non-finite numeric metadata.
        json.loads(content)
        return bytes(content)


def _cursor(page: _Page) -> str | None:
    """Resolve a bounded native cursor without silently skipping subsequent pages."""
    if page.last_id:
        return page.last_id
    return page.data[-1].id if page.data else None


def _next_cursor(page: _Page, cursors: set[str]) -> str:
    """Reject malformed or repeated pagination cursors instead of truncating results."""
    cursor = _cursor(page)
    if cursor is None or cursor in cursors:
        raise DockSightError("partial_catalog", "Model catalog pagination is incomplete", ErrorKind.DEPENDENCY)
    return cursor


def _parameters(provider: str, cursor: str) -> dict[str, str]:
    """Use the provider's native cursor field without following untrusted response URLs."""
    return {"after_id" if provider == "anthropic" else "after": cursor, "limit": "100"}


def _path(provider: str) -> str:
    """Select the provider's metadata path relative to its configured endpoint."""
    return "v1/models" if provider == "anthropic" else "models"
