import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Final, Literal, Self
from urllib.parse import urlparse

import httpx
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from docksight.adapters.outbound.audit import JsonAudit
from docksight.adapters.outbound.docker.hosts import load_hosts
from docksight.adapters.outbound.docker.runtime import DockerRuntime
from docksight.adapters.outbound.memory.actions import MemoryActions
from docksight.adapters.outbound.memory.browser_sessions import MemoryBrowserSessions
from docksight.adapters.outbound.memory.sessions import MemorySessions
from docksight.adapters.outbound.models.anthropic import AnthropicModel
from docksight.adapters.outbound.models.compatible import CompatibleModel
from docksight.adapters.outbound.models.ollama import OllamaModel
from docksight.adapters.outbound.models.openai import OpenAIModel
from docksight.adapters.outbound.models.status import ModelAvailability
from docksight.application.actions import Actions
from docksight.application.browser_sessions import BrowserSessions
from docksight.application.diagnostics.use_case import Diagnostics
from docksight.application.model_choices import ModelChoices
from docksight.application.ports.browser_sessions import BrowserSessionStore
from docksight.application.ports.models import ModelPort
from docksight.application.ports.runtime import RuntimeMutationPort, RuntimeReadPort
from docksight.application.ports.status import ModelStatusPort
from docksight.application.queries import RuntimeQueries
from docksight.application.redaction import Redactor
from docksight.application.system_status import SystemStatus
from docksight.application.views.assembler import ViewAssembler

DEFAULT_ACTOR: Final = "operator"
ACTOR_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
MIN_TOKEN_LENGTH: Final = 24


class Settings(BaseSettings):
    """Validate environment-based credentials, provider selection, and resource budgets."""

    model_config = SettingsConfigDict(
        env_prefix="DOCKSIGHT_", env_file=".env", extra="ignore", hide_input_in_errors=True, populate_by_name=True
    )

    api_token: SecretStr = SecretStr("")
    api_tokens: dict[str, SecretStr] = Field(default_factory=dict, max_length=32)
    provider: Literal["ollama", "openai", "anthropic", "compatible", "gemini"] = "ollama"
    model: str = Field(default="qwen3.5:9b", min_length=1, max_length=256)
    model_base_url: str | None = None
    model_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("DOCKSIGHT_OPENAI_API_KEY", "OPENAI_API_KEY")
    )
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("DOCKSIGHT_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    )
    gemini_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("DOCKSIGHT_GEMINI_API_KEY", "GEMINI_API_KEY")
    )
    compatible_api_key: SecretStr | None = None
    ollama_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    anthropic_base_url: str | None = None
    gemini_base_url: str | None = None
    compatible_base_url: str | None = None
    ollama_base_url: str | None = None
    compatible_structured_output: Literal["native", "tool"] = "native"
    gemini_structured_output: Literal["native", "tool"] = "native"
    provider_fallback_models: dict[str, tuple[str, ...]] = Field(default_factory=dict, max_length=5)
    hosts_file: str | None = None
    cors_origins: tuple[str, ...] = ()
    browser_origin: str | None = Field(default=None, min_length=1, max_length=2048)
    cookie_secure: bool = True
    browser_session_ttl: int = Field(default=28800, ge=60, le=28800)
    browser_session_idle_ttl: int = Field(default=3600, ge=60, le=3600)
    env_allowlist: tuple[str, ...] = ()
    max_model_calls: int = Field(default=6, ge=2, le=30)
    max_tool_calls: int = Field(default=12, ge=1, le=100)
    log_lines: int = Field(default=200, ge=1, le=2000)
    log_bytes: int = Field(default=65536, ge=1024, le=1048576)
    turn_timeout: float = Field(default=180, gt=0, le=900)
    model_timeout: float = Field(default=60, gt=0, le=300)
    model_max_tokens: int = Field(default=4096, ge=256, le=32768)
    ollama_context_length: int = Field(default=16384, ge=4096, le=262144)
    docker_timeout: float = Field(default=15, gt=0, le=120)
    action_timeout: float = Field(default=30, gt=0, le=300)
    action_ttl: int = Field(default=300, ge=1, le=3600)
    state_ttl: int = Field(default=1800, ge=60, le=86400)
    max_sessions: int = Field(default=100, ge=1, le=10000)
    max_actions: int = Field(default=1000, ge=1, le=100000)
    max_concurrent_turns: int = Field(default=4, ge=1, le=32)
    model_supports_tools: bool = True
    model_structured_output: Literal["native", "tool"] = "native"

    @model_validator(mode="after")
    def validate_credentials(self) -> Self:
        """Require at least one operator credential, each long, unique, and bound to a safe actor name."""
        if self.api_token.get_secret_value() and DEFAULT_ACTOR in self.api_tokens:
            raise ValueError(f"DOCKSIGHT_API_TOKENS cannot redefine the {DEFAULT_ACTOR!r} actor of DOCKSIGHT_API_TOKEN")
        _check_credentials(self.api_credentials())
        return self

    def api_credentials(self) -> dict[str, str]:
        """Map each authenticated actor to its bearer token, including the single-token default."""
        credentials = {actor: token.get_secret_value() for actor, token in self.api_tokens.items()}
        if self.api_token.get_secret_value():
            credentials[DEFAULT_ACTOR] = self.api_token.get_secret_value()
        return credentials

    @field_validator("browser_origin")
    @classmethod
    def validate_browser_origin(cls, value: str | None) -> str | None:
        """Require an exact public HTTP(S) origin without path or embedded authority."""
        if value is None:
            return None
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or value != f"{parsed.scheme}://{parsed.netloc}"
        ):
            raise ValueError("Browser origin must be an exact HTTP(S) origin without credentials or a path")
        _ = parsed.port
        return value

    @model_validator(mode="after")
    def validate_cookie_settings(self) -> Self:
        """Limit insecure cookie issuance to explicitly configured loopback HTTP development."""
        if not self.cookie_secure and not _loopback_http_origin(self.browser_origin):
            raise ValueError("Insecure cookies require an explicit loopback HTTP browser origin")
        return self

    @field_validator("provider_fallback_models")
    @classmethod
    def validate_fallbacks(cls, value: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
        """Bound explicit provider aliases independently of external metadata availability."""
        for provider, models in value.items():
            if provider not in {"ollama", "openai", "anthropic", "gemini", "compatible"}:
                raise ValueError("Unknown fallback provider")
            if len(models) > 100 or any(not model or len(model) > 256 for model in models):
                raise ValueError("Provider fallback models require at most 100 bounded model IDs")
        return value

    @field_validator(
        "model_base_url",
        "openai_base_url",
        "anthropic_base_url",
        "gemini_base_url",
        "compatible_base_url",
        "ollama_base_url",
    )
    @classmethod
    def validate_model_url(cls, value: str | None) -> str | None:
        """Reject provider URLs with credentials, queries, fragments, or invalid schemes."""
        if value is not None:
            parsed = urlparse(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Model endpoint must be an HTTP(S) URL without credentials or query parameters")

        return value


def _check_credentials(credentials: Mapping[str, str]) -> None:
    """Reject missing, short, shared, or log-unsafe API credentials without echoing token values."""
    if not credentials:
        raise ValueError("Configure DOCKSIGHT_API_TOKEN or DOCKSIGHT_API_TOKENS")
    if any(not ACTOR_PATTERN.fullmatch(actor) for actor in credentials):
        raise ValueError("Actor names require 1-64 letters, digits, dots, underscores, or hyphens")
    if any(len(token) < MIN_TOKEN_LENGTH for token in credentials.values()):
        raise ValueError(f"API tokens must contain at least {MIN_TOKEN_LENGTH} characters")
    if len(set(credentials.values())) != len(credentials):
        raise ValueError("Each actor requires a distinct API token")


def _loopback_http_origin(origin: str | None) -> bool:
    """Recognize configured loopback addresses without DNS lookup or forwarded headers."""
    parsed = urlparse(origin or "")
    if parsed.scheme != "http" or parsed.hostname is None:
        return False
    if parsed.hostname == "localhost":
        return True
    try:
        return ip_address(parsed.hostname).is_loopback
    except ValueError:
        return False


@dataclass
class Components:
    """Own wired application services and the cleanup callbacks for their adapters."""

    queries: RuntimeQueries
    diagnostics: Diagnostics
    actions: Actions
    status: SystemStatus
    closers: list[Callable[[], Awaitable[None]]]
    browser_sessions: BrowserSessions
    models: ModelChoices | None = None

    async def close(self) -> None:
        """Drain action work before closing adapters in reverse construction order."""
        await self.actions.close()
        if self.models is not None:
            await self.models.close()
        for close in reversed(self.closers):
            await close()


def configure_logging() -> None:
    """Configure the application logger once without propagating to root handlers."""
    logger = logging.getLogger("docksight")
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _provider_key(settings: Settings) -> str | None:
    """Resolve explicit credentials before the selected provider's own key, never another provider's key."""
    secret: SecretStr | None = getattr(settings, f"{settings.provider}_api_key")
    for candidate in (settings.model_api_key, secret):
        if candidate and candidate.get_secret_value():
            return candidate.get_secret_value()
    return None


def _openai_model(
    settings: Settings, key: str | None, closers: list[Callable[[], Awaitable[None]]]
) -> tuple[ModelPort, ModelStatusPort]:
    """Wire the native Responses adapter or a configured compatible endpoint."""
    if settings.provider == "compatible":
        if not settings.model_base_url:
            raise ValueError("Compatible providers require DOCKSIGHT_MODEL_BASE_URL")
        key = key or "local-no-key"
    if not key:
        if settings.provider == "gemini":
            raise ValueError("Configure DOCKSIGHT_MODEL_API_KEY or GEMINI_API_KEY")
        raise ValueError("Configure DOCKSIGHT_MODEL_API_KEY or OPENAI_API_KEY")
    base_url = settings.model_base_url
    if settings.provider == "gemini":
        base_url = base_url or "https://generativelanguage.googleapis.com/v1beta/openai/"
    client = AsyncOpenAI(
        api_key=key,
        base_url=base_url,
        timeout=settings.model_timeout,
        max_retries=0,
    )
    closers.append(client.close)
    probe = _build_probe(settings, str(client.base_url), {**client.auth_headers, **client.default_headers}, closers)
    if settings.provider == "openai":
        return OpenAIModel(client, settings.model, settings.model_max_tokens), probe
    return CompatibleModel(
        client,
        settings.model,
        settings.model_max_tokens,
        settings.model_structured_output,
        require_tool_signatures=settings.provider == "gemini",
    ), probe


def _build_model(
    settings: Settings, key: str | None, closers: list[Callable[[], Awaitable[None]]]
) -> tuple[ModelPort, ModelStatusPort]:
    """Validate model capabilities and register the selected client's cleanup."""
    if not settings.model_supports_tools:
        raise ValueError("Docker diagnostics require a model with tool-calling support")
    if settings.model_structured_output == "tool" and settings.provider not in {"compatible", "gemini"}:
        raise ValueError("Tool-based structured output requires provider=compatible or provider=gemini")
    if settings.provider == "ollama":
        client = httpx.AsyncClient(
            base_url=settings.model_base_url or "http://127.0.0.1:11434",
            timeout=settings.model_timeout,
            headers={"Authorization": f"Bearer {key}"} if key else {},
        )
        closers.append(client.aclose)
        probe = _build_probe(settings, str(client.base_url), dict(client.headers), closers)
        return OllamaModel(client, settings.model, settings.model_max_tokens, settings.ollama_context_length), probe
    if settings.provider == "anthropic":
        if not key:
            raise ValueError("Configure DOCKSIGHT_MODEL_API_KEY or ANTHROPIC_API_KEY")
        anthropic_client = AsyncAnthropic(
            api_key=key,
            base_url=settings.model_base_url,
            timeout=settings.model_timeout,
            max_retries=0,
        )
        closers.append(anthropic_client.close)
        probe = _build_probe(
            settings,
            str(anthropic_client.base_url),
            {**anthropic_client.auth_headers, **anthropic_client.default_headers},
            closers,
        )
        return AnthropicModel(anthropic_client, settings.model, settings.model_max_tokens), probe
    return _openai_model(settings, key, closers)


def _build_probe(
    settings: Settings,
    base_url: str,
    headers: Mapping[str, object],
    closers: list[Callable[[], Awaitable[None]]],
) -> ModelStatusPort:
    """Wire a bounded metadata client with the same server configuration as generation."""
    client = httpx.AsyncClient(
        base_url=base_url,
        headers={name: value for name, value in headers.items() if isinstance(value, str)},
        timeout=2,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
    )
    closers.append(client.aclose)
    return ModelAvailability(client, settings.provider, settings.model)


def build_components(
    settings: Settings,
    *,
    reader: RuntimeReadPort | None = None,
    writer: RuntimeMutationPort | None = None,
    model: ModelPort | None = None,
    model_probe: ModelStatusPort | None = None,
    browser_session_store: BrowserSessionStore | None = None,
) -> Components:
    """Wire hexagonal services with configured adapters or explicitly injected test ports."""
    configure_logging()
    effective_key = _provider_key(settings)
    secrets = tuple(settings.api_credentials().values())
    secrets = (
        *secrets,
        *(
            value.get_secret_value()
            for value in (
                settings.openai_api_key,
                settings.anthropic_api_key,
                settings.gemini_api_key,
                settings.compatible_api_key,
                settings.ollama_api_key,
            )
            if value and value.get_secret_value()
        ),
    )
    if effective_key:
        secrets = (*secrets, effective_key)
    redactor = Redactor(secrets)
    closers: list[Callable[[], Awaitable[None]]] = []
    if reader is None:
        runtime = DockerRuntime(
            load_hosts(settings.hosts_file),
            redactor,
            settings.env_allowlist,
            settings.docker_timeout,
        )
        reader, writer = runtime, runtime
        closers.append(runtime.close)
    if writer is None:
        raise ValueError("A runtime mutation adapter must be supplied with a custom reader")
    if model is None:
        model, configured_probe = _build_model(settings, effective_key, closers)
        if model_probe is None:
            model_probe = configured_probe
    actions = Actions(
        reader,
        writer,
        MemoryActions(settings.max_actions, settings.state_ttl),
        JsonAudit(redactor),
        settings.action_ttl,
        settings.action_timeout,
    )
    diagnostics = Diagnostics(
        reader,
        model,
        MemorySessions(settings.max_sessions, settings.state_ttl),
        redactor,
        ViewAssembler(actions.prepare),
        settings.max_model_calls,
        settings.max_tool_calls,
        settings.turn_timeout,
        settings.log_lines,
        settings.log_bytes,
        settings.max_concurrent_turns,
        model_identity=(settings.provider, settings.model),
    )

    from docksight.bootstrap_models import build_choices

    choices = build_choices(settings, model, model_probe, closers, _build_model)
    return Components(
        RuntimeQueries(reader, settings.log_lines, settings.log_bytes),
        diagnostics,
        actions,
        SystemStatus(reader, model_probe, settings.provider, settings.model),
        closers,
        BrowserSessions(
            browser_session_store if browser_session_store is not None else MemoryBrowserSessions(),
            settings.browser_session_ttl,
            settings.browser_session_idle_ttl,
        ),
        choices,
    )
