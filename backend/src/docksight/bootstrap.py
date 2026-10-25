from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCKSIGHT_", env_file=".env", extra="ignore")

    api_token: SecretStr = SecretStr("")
    provider: Literal["ollama", "openai", "anthropic", "compatible"] = "ollama"
    model: str = Field(default="qwen3.5:9b", min_length=1)
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
        if len(value.get_secret_value()) < 24:
            raise ValueError("API token must contain at least 24 characters")

        return value
