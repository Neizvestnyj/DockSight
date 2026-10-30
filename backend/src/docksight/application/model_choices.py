from collections.abc import Callable

from docksight.application.model_catalog import CatalogCache, CatalogView, ModelSelection, ProvidersView
from docksight.application.ports.models import ModelPort
from docksight.application.ports.status import ModelStatusPort
from docksight.domain.errors import DockSightError


class ModelChoices:
    """Validate optional selections before resolving shared configured provider connections."""

    def __init__(
        self,
        providers: ProvidersView,
        catalogs: dict[str, CatalogCache],
        resolve: Callable[[ModelSelection], tuple[ModelPort, ModelStatusPort | None]],
    ) -> None:
        """Keep server-owned catalogs and the composition root's bounded client resolver."""
        self.providers = providers
        self.catalogs = catalogs
        self.resolve = resolve

    def _catalog(self, provider: str) -> CatalogCache:
        """Reject unknown or unconfigured providers without making external requests."""
        catalog = self.catalogs.get(provider)
        if catalog is None:
            raise DockSightError("provider_not_configured", "Select a configured model provider", 422)
        return catalog

    async def catalog(self, provider: str, refresh: bool = False) -> CatalogView:
        """Read one lazily fetched provider catalog."""
        return await self._catalog(provider).get(refresh)

    async def select(self, selection: ModelSelection) -> tuple[ModelPort, ModelStatusPort | None]:
        """Validate identity and membership before generation or status work."""
        await self._catalog(selection.provider).validate(selection.model)
        return self.resolve(selection)

    async def close(self) -> None:
        """Drain all background catalog refreshes before adapter cleanup."""
        for catalog in self.catalogs.values():
            await catalog.close()
