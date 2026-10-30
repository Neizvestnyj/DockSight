import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import httpx
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from docksight.adapters.outbound.audit import JsonAudit
from docksight.adapters.outbound.docker.hosts import load_hosts
from docksight.adapters.outbound.docker.runtime import DockerRuntime
from docksight.adapters.outbound.memory.actions import MemoryActions
from docksight.adapters.outbound.memory.sessions import MemorySessions
from docksight.adapters.outbound.models.anthropic import AnthropicModel
from docksight.adapters.outbound.models.compatible import CompatibleModel
from docksight.adapters.outbound.models.ollama import OllamaModel
from docksight.adapters.outbound.models.openai import OpenAIModel
from docksight.adapters.outbound.models.status import ModelAvailability
from docksight.application.actions import Actions
from docksight.application.diagnostics.use_case import Diagnostics
from docksight.application.ports.models import ModelPort
from docksight.application.ports.runtime import RuntimeMutationPort, RuntimeReadPort
from docksight.application.ports.status import ModelStatusPort
from docksight.application.queries import RuntimeQueries
from docksight.application.redaction import Redactor
from docksight.application.system_status import SystemStatus
from docksight.application.views.assembler import ViewAssembler


class Settings(BaseSettings):
    """Validate environment-based credentials, provider selection, and resource budgets."""

    model_config = SettingsConfigDict(
        env_prefix="DOCKSIGHT_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    api_token: SecretStr = SecretStr("")
    provider: Literal["ollama", "openai", "anthropic", "compatible", "gemini"] = "ollama"
    model: str = Field(default="qwen3.5:9b", min_length=1, max_length=256)
    model_base_url: str | None = None
    model_api_key: SecretStr | None = None
    hosts_file: str | None = None
    cors_origins: tuple[str, ...] = ()
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

    @field_validator("api_token")
    @classmethod
    def validate_token(cls, value: SecretStr) -> SecretStr:
        """Reject API tokens shorter than the minimum operator credential length."""
        if len(value.get_secret_value()) < 24:
            raise ValueError("API token must contain at least 24 characters")

        return value

    @field_validator("model_base_url")
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


@dataclass
class Components:
    """Own wired application services and the cleanup callbacks for their adapters."""

    queries: RuntimeQueries
    diagnostics: Diagnostics
    actions: Actions
    status: SystemStatus
    closers: list[Callable[[], Awaitable[None]]]

    async def close(self) -> None:
        """Drain action work before closing adapters in reverse construction order."""
        await self.actions.close()
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
    """Resolve explicit credentials before provider-specific environment defaults."""
    if settings.model_api_key and settings.model_api_key.get_secret_value():
        return settings.model_api_key.get_secret_value()
    if settings.provider == "anthropic":
        return os.getenv("ANTHROPIC_API_KEY")
    if settings.provider == "gemini":
        return os.getenv("GEMINI_API_KEY")
    if settings.provider in {"openai", "compatible"}:
        return os.getenv("OPENAI_API_KEY")
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
) -> Components:
    """Wire hexagonal services with configured adapters or explicitly injected test ports."""
    configure_logging()
    effective_key = _provider_key(settings)
    secrets = (settings.api_token.get_secret_value(),)
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

    return Components(
        RuntimeQueries(reader, settings.log_lines, settings.log_bytes),
        diagnostics,
        actions,
        SystemStatus(reader, model_probe, settings.provider, settings.model),
        closers,
    )
