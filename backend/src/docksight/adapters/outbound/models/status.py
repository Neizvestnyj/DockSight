from typing import Final, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field, ValidationError

from docksight.application.ports.status import CheckCode, ProbeResult

MAX_METADATA_BYTES: Final = 262144


class _ModelId(BaseModel):
    """Read only the bounded public identity from native model metadata."""

    id: str = Field(min_length=1, max_length=256)


class _Catalog(BaseModel):
    """Validate a finite compatible catalog without assuming it lists every alias."""

    data: list[_ModelId] = Field(max_length=2000)


class _OpenAIInfo(_ModelId):
    """Require an actual OpenAI model object rather than an unrelated success document."""

    object: Literal["model"]


class _AnthropicInfo(_ModelId):
    """Recognize an Anthropic model object, including resolved aliases."""

    type: Literal["model"]


class _OllamaInfo(BaseModel):
    """Recognize native show metadata without retaining its template or file paths."""

    details: dict[str, object]
    model_info: dict[str, object]


class ModelAvailability:
    """Probe provider metadata using the configured client without generation or mutation."""

    def __init__(self, client: httpx.AsyncClient, provider: str, model: str) -> None:
        """Reuse a private bounded HTTP client and the exact server-selected model name."""
        self.client = client
        self.provider = provider
        self.model = model

    async def check(self) -> tuple[ProbeResult, ProbeResult]:
        """Return public result codes and discard every upstream response body."""
        try:
            status, content = await self._metadata()
        except httpx.TimeoutException:
            return self._unavailable("timeout")
        except httpx.HTTPError:
            return self._unavailable("connection_failed")
        if status == 200:
            return self._success(content)
        return self._failure(status)

    async def _metadata(self) -> tuple[int, bytes]:
        """Bound metadata response memory and avoid redirects, retries, or generation routes."""
        method, path = "GET", f"models/{quote(self.model, safe='')}"
        body: dict[str, str] | None = None
        if self.provider == "ollama":
            method, path, body = "POST", "api/show", {"model": self.model}
        elif self.provider == "compatible":
            path = "models"
        elif self.provider == "anthropic":
            path = f"v1/{path}"
        async with self.client.stream(method, path, json=body, timeout=2, follow_redirects=False) as response:
            if response.status_code != 200:
                return response.status_code, b""
            content = bytearray()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > MAX_METADATA_BYTES:
                    return 200, b""
                content.extend(chunk)
        return 200, bytes(content)

    def _success(self, content: bytes) -> tuple[ProbeResult, ProbeResult]:
        """Recognize metadata rather than treating any HTTP 200 page as a valid model."""
        reachable = ProbeResult("available", "ok")
        try:
            if self.provider == "compatible":
                catalog = _Catalog.model_validate_json(content)
                if self.model not in {item.id for item in catalog.data}:
                    return reachable, ProbeResult("not_checked", "model_not_listed")
            elif self.provider == "ollama":
                _OllamaInfo.model_validate_json(content)
            elif self.provider == "anthropic":
                _AnthropicInfo.model_validate_json(content)
            else:
                _OpenAIInfo.model_validate_json(content)
        except ValidationError:
            unknown = ProbeResult("not_checked", "invalid_response")
            return unknown, unknown
        return reachable, ProbeResult("available", "ok")

    def _failure(self, status: int) -> tuple[ProbeResult, ProbeResult]:
        """Distinguish missing native models from unsupported compatible metadata routes."""
        reachable = ProbeResult("available", "ok")
        if status == 403:
            return reachable, ProbeResult("not_checked", "metadata_forbidden")
        if status in {404, 405, 501}:
            if status == 404 and self.provider != "compatible":
                return reachable, ProbeResult("unavailable", "model_not_found")
            return ProbeResult("not_checked", "unsupported"), ProbeResult("not_checked", "unsupported")
        if status == 401:
            return self._unavailable("credentials_rejected")
        if status == 429:
            return self._unavailable("rate_limited")
        return self._unavailable("upstream_error")

    @staticmethod
    def _unavailable(code: CheckCode) -> tuple[ProbeResult, ProbeResult]:
        """Avoid claiming model unavailability when its provider could not be checked."""
        return ProbeResult("unavailable", code), ProbeResult("not_checked", "provider_unavailable")
