import asyncio

import pytest

from docksight.application.model_catalog import CatalogCache
from docksight.domain.errors import DockSightError


async def test_catalog_coalesces_and_reuses_fresh_rows() -> None:
    """One metadata fetch serves concurrent readers and the subsequent TTL window."""
    calls = 0

    async def fetch() -> tuple[str, ...]:
        """Yield control to exercise concurrent request coalescing."""
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return ("listed",)

    cache = CatalogCache("ollama", ("default",), fetch)
    first, second = await asyncio.gather(cache.get(), cache.get(refresh=True))
    assert first == second
    assert {row.id for row in first.models} == {"default", "listed"}
    assert (await cache.get()).state == "ready"
    assert calls == 1
    await cache.close()


async def test_stale_refresh_failure_retains_rows_and_cools_down() -> None:
    """A refresh error preserves the prior catalog and suppresses repeated manual requests."""
    clock = [0.0]
    calls = 0

    async def fetch() -> tuple[str, ...]:
        """Succeed once, then simulate a denied metadata request."""
        nonlocal calls
        calls += 1
        if calls > 1:
            raise DockSightError("metadata_forbidden", "Private upstream text", 502)
        return ("listed",)

    cache = CatalogCache("openai", ("alias",), fetch, clock=lambda: clock[0])
    await cache.get()
    clock[0] = 301
    await cache.get()
    assert cache.task is not None
    await cache.task
    result = await cache.get(refresh=True)
    assert result.state == "stale"
    assert result.code == "metadata_forbidden"
    assert [row.id for row in result.models] == ["alias", "listed"]
    assert calls == 2
    await cache.validate("alias")
    assert calls == 2
    await cache.close()


async def test_shutdown_cancels_initial_catalog_work() -> None:
    """Shutdown owns and cancels background work even when an HTTP waiter is cancelled."""
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def fetch() -> tuple[str, ...]:
        """Record cancellation of a pending provider request."""
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return ()

    cache = CatalogCache("ollama", (), fetch)
    waiter = asyncio.create_task(cache.get())
    await entered.wait()
    waiter.cancel()
    await asyncio.gather(waiter, return_exceptions=True)
    assert not cancelled.is_set()
    await cache.close()
    assert cancelled.is_set()


async def test_catalog_total_deadline_cancels_provider_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """The total deadline bounds an indefinitely pending metadata operation."""
    timeout = asyncio.timeout

    def short_timeout(seconds: float):
        """Use a short real deadline while verifying the production timeout argument."""
        assert seconds == 5
        return timeout(0.01)

    async def fetch() -> tuple[str, ...]:
        """Simulate a provider that never finishes returning metadata."""
        await asyncio.Event().wait()
        return ()

    monkeypatch.setattr("docksight.application.model_catalog.asyncio.timeout", short_timeout)
    cache = CatalogCache("ollama", ("default",), fetch)
    result = await cache.get()
    assert result.code == "timeout"
    assert not result.refreshing
    await cache.close()


async def test_catalog_failure_retains_fallback_and_cools_down() -> None:
    """Catalog failure never removes an explicitly configured usable model."""
    calls = 0

    async def fetch() -> tuple[str, ...]:
        """Simulate an unavailable metadata endpoint."""
        nonlocal calls
        calls += 1
        raise TimeoutError

    cache = CatalogCache("ollama", ("default",), fetch)
    result = await cache.get()
    assert result.state == "unavailable"
    assert result.code == "timeout"
    assert [row.id for row in result.models] == ["default"]
    await cache.get(refresh=True)
    assert calls == 1
    await cache.close()


@pytest.mark.parametrize("age", [301, 1000])
async def test_stale_catalog_returns_immediately_during_refresh(age: float) -> None:
    """Stale rows remain selectable while a single background task refreshes them."""
    clock = [0.0]
    release = asyncio.Event()
    calls = 0

    async def fetch() -> tuple[str, ...]:
        """Block only the refresh so stale response latency can be checked."""
        nonlocal calls
        calls += 1
        if calls > 1:
            await release.wait()
        return ("listed",)

    cache = CatalogCache("ollama", (), fetch, clock=lambda: clock[0])
    await cache.get()
    clock[0] = age
    stale = await asyncio.wait_for(cache.get(), 0.1)
    assert stale.state == "stale"
    assert stale.refreshing
    assert stale.models[0].id == "listed"
    await cache.close()
