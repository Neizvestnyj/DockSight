import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import monotonic
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from docksight.domain.errors import DockSightError, ErrorKind


class ModelSelection(BaseModel):
    """Identify a server-configured provider and bounded model without connection details."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=256)


class ModelId(BaseModel):
    """Expose only a public metadata identity, without asserting model capabilities."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1, max_length=256)


class ProviderView(BaseModel):
    """Describe configured availability without disclosing endpoints or credentials."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    configured: bool
    default_model: str | None = Field(default=None, min_length=1, max_length=256)


class ProvidersView(BaseModel):
    """Publish supported providers and the legacy default selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    default: ModelSelection
    providers: tuple[ProviderView, ...] = Field(max_length=5)


class CatalogView(BaseModel):
    """Report bounded metadata freshness separately from generation availability."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    provider: str = Field(min_length=1, max_length=32)
    models: tuple[ModelId, ...] = Field(max_length=2000)
    state: Literal["ready", "stale", "unavailable"]
    code: str = Field(min_length=1, max_length=64)
    checked_at: AwareDatetime | None
    refreshing: bool


class CatalogCache:
    """Coalesce bounded metadata work and preserve rows through stale refresh failures."""

    def __init__(
        self,
        provider: str,
        fallback: tuple[str, ...],
        fetch: Callable[[], Awaitable[tuple[str, ...]]],
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        """Bind one immutable connection identity and its explicitly configured fallback IDs."""
        self.provider = provider
        self.fallback = fallback
        self.fetch = fetch
        self.clock = clock
        self.rows = fallback
        self.checked_at: datetime | None = None
        self.updated: float | None = None
        self.retry_at = 0.0
        self.code = "not_checked"
        self.task: asyncio.Task[None] | None = None
        self.closed = False

    async def get(self, refresh: bool = False) -> CatalogView:
        """Return stale rows immediately, awaiting only an initial coalesced metadata fetch."""
        stale = self.updated is None or self.clock() - self.updated >= 300
        if not self.closed and (refresh or stale) and self.clock() >= self.retry_at:
            if self.task is None or self.task.done():
                self.task = asyncio.create_task(self._refresh())
        if self.updated is None and self.task is not None:
            await asyncio.shield(self.task)
        return self._view()

    def _view(self) -> CatalogView:
        """Snapshot safe public rows and freshness without private exception text."""
        refreshing = self.task is not None and not self.task.done()
        stale = self.updated is None or self.clock() - self.updated >= 300 or self.code != "ok"
        state = "unavailable" if self.updated is None else "stale" if stale else "ready"
        return CatalogView(
            provider=self.provider,
            models=tuple(ModelId(id=value) for value in self.rows),
            state=state,
            code=self.code,
            checked_at=self.checked_at,
            refreshing=refreshing,
        )

    async def _refresh(self) -> None:
        """Apply a total deadline and failure cooldown without discarding prior successful rows."""
        try:
            async with asyncio.timeout(5):
                rows = await self.fetch()
            combined = tuple(dict.fromkeys((*self.fallback, *rows)))
            if len(combined) > 2000:
                raise DockSightError(
                    "partial_catalog", "Model catalog exceeds the supported model count", ErrorKind.DEPENDENCY
                )
            self.rows = combined
            self.updated = self.clock()
            self.code = "ok"
        except TimeoutError:
            self.code = "timeout"
        except DockSightError as error:
            self.code = error.code
        finally:
            self.checked_at = datetime.now(UTC)
            self.retry_at = self.clock() + (30 if self.code != "ok" else 0)

    async def validate(self, model: str) -> None:
        """Allow explicit fallbacks without requiring metadata endpoint availability."""
        if model in self.fallback:
            return
        view = await self.get()
        if model not in {row.id for row in view.models}:
            raise DockSightError(
                "model_not_listed", "Select a model from the configured provider catalog", ErrorKind.VALIDATION
            )

    async def close(self) -> None:
        """Cancel metadata work before the owning HTTP clients close."""
        self.closed = True
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
