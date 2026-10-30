import httpx
import pytest

from docksight.adapters.outbound.models.catalog import ModelCatalog
from docksight.domain.errors import DockSightError


@pytest.mark.parametrize("provider", ["openai", "compatible", "gemini", "anthropic"])
async def test_model_catalog_reads_every_native_page(provider: str) -> None:
    """Pagination follows IDs on the configured origin and retains every model."""
    calls: list[httpx.Request] = []

    def reply(request: httpx.Request) -> httpx.Response:
        """Return two metadata pages using a deterministic native cursor."""
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={"data": [{"id": "first"}], "has_more": True, "last_id": "first"})
        return httpx.Response(200, json={"data": [{"id": "second"}], "has_more": False})

    async with httpx.AsyncClient(base_url="https://provider.test/", transport=httpx.MockTransport(reply)) as client:
        assert await ModelCatalog(client, provider).fetch() == ("first", "second")
    assert calls[0].url.path == ("/v1/models" if provider == "anthropic" else "/models")
    assert calls[1].url.params["after_id" if provider == "anthropic" else "after"] == "first"


async def test_ollama_catalog_uses_native_tags() -> None:
    def reply(request: httpx.Request) -> httpx.Response:
        """Return native tags rather than compatible metadata."""
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen:latest"}]})

    async with httpx.AsyncClient(base_url="http://local/", transport=httpx.MockTransport(reply)) as client:
        assert await ModelCatalog(client, "ollama").fetch() == ("qwen:latest",)


@pytest.mark.parametrize(
    "content",
    [b"not-json", b"{}", b'{"data":[{"id":""}]}', b"x" * 262145],
    ids=["invalid-json", "missing-data", "empty-id", "oversized"],
)
async def test_catalog_rejects_malformed_or_oversized_metadata(content: bytes) -> None:
    async with httpx.AsyncClient(
        base_url="http://local/", transport=httpx.MockTransport(lambda _: httpx.Response(200, content=content))
    ) as client:
        with pytest.raises(DockSightError, match="metadata") as error:
            await ModelCatalog(client, "openai").fetch()
    assert error.value.code == "invalid_response"


async def test_repeated_pagination_is_explicitly_partial() -> None:
    async with httpx.AsyncClient(
        base_url="http://local/",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": [{"id": "same"}], "has_more": True})),
    ) as client:
        with pytest.raises(DockSightError) as error:
            await ModelCatalog(client, "anthropic").fetch()
    assert error.value.code == "partial_catalog"


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "credentials_rejected"),
        (403, "metadata_forbidden"),
        (404, "unsupported"),
        (429, "rate_limited"),
        (500, "upstream_error"),
    ],
)
async def test_catalog_failures_use_safe_codes(status: int, code: str) -> None:
    async with httpx.AsyncClient(
        base_url="http://private/", transport=httpx.MockTransport(lambda _: httpx.Response(status, text="secret-key"))
    ) as client:
        with pytest.raises(DockSightError) as error:
            await ModelCatalog(client, "compatible").fetch()
    assert error.value.code == code
    assert "secret-key" not in str(error.value)
