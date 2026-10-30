import json

import httpx
import pytest

from docksight.adapters.outbound.models.status import ModelAvailability


@pytest.mark.parametrize("provider", ["ollama", "openai", "anthropic", "compatible", "gemini"])
async def test_checks_use_metadata_only_and_keep_model_identity(provider: str) -> None:
    calls: list[httpx.Request] = []

    def metadata(request: httpx.Request) -> httpx.Response:
        """Return native metadata and reject any attempted generation route."""
        calls.append(request)
        assert request.url.path in {"/api/show", "/models/model", "/v1/models/model", "/models"}
        if provider == "ollama":
            assert request.method == "POST"
            assert json.loads(request.content) == {"model": "model"}
            return httpx.Response(200, json={"details": {}, "model_info": {}})
        assert request.method == "GET"
        if provider == "compatible":
            return httpx.Response(200, json={"data": [{"id": "model"}]})
        return httpx.Response(200, json={"id": "resolved-alias", "object": "model", "type": "model"})

    async with httpx.AsyncClient(base_url="http://private-provider", transport=httpx.MockTransport(metadata)) as client:
        checks = await ModelAvailability(client, provider, "model").check()
    assert [check.state for check in checks] == ["available", "available"]
    assert len(calls) == 1


@pytest.mark.parametrize("status", [403, 404, 405, 501])
async def test_unsupported_compatible_metadata_is_not_model_unavailability(status: int) -> None:
    async with httpx.AsyncClient(
        base_url="http://private-provider",
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text="private-key private-host")),
    ) as client:
        provider, model = await ModelAvailability(client, "compatible", "model").check()
    assert model.state == "not_checked"
    assert "private" not in model.code
    assert provider.state != "unavailable"


@pytest.mark.parametrize("status,code", [(401, "credentials_rejected"), (429, "rate_limited"), (503, "upstream_error")])
async def test_upstream_failure_does_not_expose_response_content(status: int, code: str) -> None:
    async with httpx.AsyncClient(
        base_url="http://private-provider",
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text="private-key private-host")),
    ) as client:
        provider, model = await ModelAvailability(client, "openai", "model").check()
    assert provider.state == "unavailable"
    assert provider.code == code
    assert model.state == "not_checked"


async def test_missing_native_model_and_unlisted_compatible_alias_are_distinct() -> None:
    async with httpx.AsyncClient(
        base_url="http://private-provider", transport=httpx.MockTransport(lambda _: httpx.Response(404))
    ) as client:
        provider, model = await ModelAvailability(client, "ollama", "model").check()
    assert provider.state == "available"
    assert model.state == "unavailable"
    assert model.code == "model_not_found"
    async with httpx.AsyncClient(
        base_url="http://private-provider",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": []})),
    ) as client:
        provider, model = await ModelAvailability(client, "compatible", "alias").check()
    assert provider.state == "available"
    assert model.state == "not_checked"
    assert model.code == "model_not_listed"


async def test_invalid_or_oversized_metadata_cannot_become_a_success() -> None:
    for response in [httpx.Response(200, json={"unexpected": True}), httpx.Response(200, content=b"x" * 262145)]:
        async with httpx.AsyncClient(
            base_url="http://private-provider", transport=httpx.MockTransport(lambda _, value=response: value)
        ) as client:
            provider, model = await ModelAvailability(client, "openai", "model").check()
        assert model.state == "not_checked"
        assert model.code == "invalid_response"
        assert provider.state == "not_checked"


async def test_transport_error_is_reported_without_leaking_connection_details() -> None:
    def offline(request: httpx.Request) -> httpx.Response:
        """Raise a transport failure containing data that must never be serialized."""
        raise httpx.ConnectError("private-host private-key", request=request)

    async with httpx.AsyncClient(base_url="http://private-provider", transport=httpx.MockTransport(offline)) as client:
        provider, model = await ModelAvailability(client, "openai", "model").check()
    assert provider.code == "connection_failed"
    assert model.state == "not_checked"
