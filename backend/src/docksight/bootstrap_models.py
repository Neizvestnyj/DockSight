from __future__ import annotations

from collections.abc import Awaitable, Callable
from copy import copy
from typing import TYPE_CHECKING, Final, Literal

from docksight.adapters.outbound.models.anthropic import AnthropicModel
from docksight.adapters.outbound.models.catalog import ModelCatalog
from docksight.adapters.outbound.models.compatible import CompatibleModel
from docksight.adapters.outbound.models.ollama import OllamaModel
from docksight.adapters.outbound.models.openai import OpenAIModel
from docksight.adapters.outbound.models.status import ModelAvailability
from docksight.application.model_catalog import CatalogCache, ModelSelection, ProvidersView, ProviderView
from docksight.application.model_choices import ModelChoices
from docksight.application.ports.models import ModelPort
from docksight.application.ports.status import ModelStatusPort
from docksight.domain.errors import DockSightError, ErrorKind

if TYPE_CHECKING:
    from docksight.bootstrap import Settings

type Provider = Literal["ollama", "openai", "anthropic", "gemini", "compatible"]
type Builder = Callable[
    ["Settings", str | None, list[Callable[[], Awaitable[None]]]], tuple[ModelPort, ModelStatusPort]
]

NAMES: Final[dict[Provider, str]] = {
    "ollama": "Ollama",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
    "compatible": "OpenAI compatible",
}
BASES: Final = {
    "ollama": "http://127.0.0.1:11434",
    "openai": "https://api.openai.com/v1/",
    "anthropic": "https://api.anthropic.com/",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}


class _Connection:
    """Lazily own one generation template and metadata connection per configured provider."""

    def __init__(
        self,
        settings: Settings,
        key: str | None,
        closers: list[Callable[[], Awaitable[None]]],
        builder: Builder,
        model: ModelPort | None = None,
        probe: ModelStatusPort | None = None,
    ) -> None:
        """Retain immutable server configuration and reuse already injected default ports."""
        self.settings = settings
        self.key = key
        self.closers = closers
        self.builder = builder
        self.model = model
        self.probe = probe

    def _ensure(self) -> None:
        """Allocate clients once, only when this configured provider is first used."""
        if self.model is None:
            self.model, self.probe = self.builder(self.settings, self.key, self.closers)

    async def fetch(self) -> tuple[str, ...]:
        """Reuse generation-aligned metadata authentication without exposing connection data."""
        self._ensure()
        if not isinstance(self.probe, ModelAvailability):
            raise DockSightError(
                "unsupported", "Model catalog is not configured for this adapter", ErrorKind.DEPENDENCY
            )
        return await ModelCatalog(self.probe.client, self.settings.provider).fetch()

    def select(self, model: str) -> tuple[ModelPort, ModelStatusPort | None]:
        """Use transient adapter copies sharing bounded clients rather than caching arbitrary model instances."""
        self._ensure()
        selected = self.model
        if isinstance(selected, (OllamaModel, OpenAIModel, CompatibleModel, AnthropicModel)):
            selected = copy(selected)
            selected.model = model
        elif model != self.settings.model:
            raise DockSightError(
                "model_not_listed", "Injected adapter only supports its configured model", ErrorKind.VALIDATION
            )
        if selected is None:
            raise DockSightError("provider_not_configured", "Provider is not configured", ErrorKind.VALIDATION)
        probe = self.probe
        if isinstance(probe, ModelAvailability):
            probe = ModelAvailability(probe.client, self.settings.provider, model)
        return selected, probe


def build_choices(
    settings: Settings,
    model: ModelPort,
    probe: ModelStatusPort | None,
    closers: list[Callable[[], Awaitable[None]]],
    builder: Builder,
) -> ModelChoices:
    """Build safe provider descriptions and lazy connection-specific in-memory catalogs."""
    connections: dict[str, _Connection] = {}
    catalogs: dict[str, CatalogCache] = {}
    views: list[ProviderView] = []
    for provider, name in NAMES.items():
        fallback = settings.provider_fallback_models.get(provider, ())
        is_default = provider == settings.provider
        config, key, configured = _configuration(settings, provider, fallback)
        fallback = _fallback(settings, fallback, is_default)
        views.append(_provider_view(provider, name, configured, fallback))
        if configured:
            connection = _Connection(
                config, key, closers, builder, model if is_default else None, probe if is_default else None
            )
            connections[provider] = connection
            catalogs[provider] = CatalogCache(provider, fallback, connection.fetch)

    def resolve(selection: ModelSelection) -> tuple[ModelPort, ModelStatusPort | None]:
        """Resolve only a membership-validated identity through a configured connection."""
        return connections[selection.provider].select(selection.model)

    return ModelChoices(
        ProvidersView(default=ModelSelection(provider=settings.provider, model=settings.model), providers=tuple(views)),
        catalogs,
        resolve,
    )


def _provider_view(provider: str, name: str, configured: bool, fallback: tuple[str, ...]) -> ProviderView:
    """Describe only public configuration and an explicitly configured fallback model."""
    return ProviderView(id=provider, name=name, configured=configured, default_model=fallback[0] if fallback else None)


def _fallback(settings: Settings, fallback: tuple[str, ...], is_default: bool) -> tuple[str, ...]:
    """Always allow the legacy default even when its metadata cannot be read."""
    return tuple(dict.fromkeys((settings.model, *fallback))) if is_default else fallback


def _configuration(
    settings: Settings, provider: Provider, fallback: tuple[str, ...]
) -> tuple[Settings, str | None, bool]:
    """Preserve legacy defaults and resolve secondary provider keys only from server settings."""
    if provider == settings.provider:
        return settings, None, True
    secret = getattr(settings, f"{provider}_api_key")
    key = secret.get_secret_value() if secret else None
    base = getattr(settings, f"{provider}_base_url")
    configured = bool(base) if provider == "compatible" else provider == "ollama" or bool(key)
    config = settings.model_copy(
        update={
            "provider": provider,
            "model": fallback[0] if fallback else settings.model,
            "model_base_url": base or BASES.get(provider),
            "model_api_key": secret,
            "model_structured_output": getattr(settings, f"{provider}_structured_output", "native"),
        }
    )
    return config, key, configured
