import asyncio
import json
import logging
import traceback
from collections.abc import Callable
from copy import copy
from datetime import UTC, datetime
from typing import Final, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from docksight.application.ports.runtime import RuntimeReadPort
from docksight.application.ports.status import CheckCode, CheckState, ModelStatusPort, ProbeResult
from docksight.domain.errors import DockSightError, ErrorKind

MESSAGES: Final[dict[CheckCode, str]] = {
    "ok": "Availability check succeeded.",
    "host_not_selected": "Select a configured host to check Docker.",
    "timeout": "The availability check timed out.",
    "connection_failed": "Could not connect to the provider.",
    "runtime_unavailable": "Could not connect to the selected Docker host.",
    "credentials_rejected": "The provider rejected its server-configured credentials.",
    "metadata_forbidden": "Model metadata access is denied; generation access was not tested.",
    "unsupported": "The provider does not expose a supported model metadata endpoint.",
    "model_not_found": "The configured model was not found by the provider.",
    "model_not_listed": "The model is not in the returned catalog; aliases and generation were not tested.",
    "rate_limited": "The provider rate-limited the availability check.",
    "upstream_error": "The provider could not complete the availability check.",
    "invalid_response": "The provider returned unsupported or oversized metadata.",
    "probe_not_configured": "Metadata checks are not configured for this model adapter.",
    "check_failed": "The availability check could not finish.",
    "provider_unavailable": "Model availability was not checked because the provider check failed.",
}


class DependencyCheck(BaseModel):
    """Expose one bounded, timestamped result without private connection details."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    state: CheckState
    code: CheckCode
    message: str = Field(max_length=256)
    checked_at: AwareDatetime


class SystemStatusView(BaseModel):
    """Report server-selected configuration and independent dependency checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    host: str | None = Field(max_length=64)
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=256)
    docker: DependencyCheck
    provider_check: DependencyCheck
    model_check: DependencyCheck


class SystemStatus:
    """Bound independent read-only checks without changing process health or diagnosis state."""

    def __init__(
        self,
        runtime: RuntimeReadPort,
        probe: ModelStatusPort | None,
        provider: str,
        model: str,
        timeout: float = 3,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind configured adapters, a short deadline, and a UTC clock."""
        self.runtime = runtime
        self.probe = probe
        self.provider = provider
        self.model = model
        self.timeout = timeout
        self.clock = clock or (lambda: datetime.now(UTC))

    def with_model(self, probe: ModelStatusPort | None, provider: str, model: str) -> Self:
        """Check the exact selection while preserving runtime and deadline configuration."""
        selected = copy(self)
        selected.probe = probe
        selected.provider = provider
        selected.model = model
        return selected

    def _view(self, result: ProbeResult) -> DependencyCheck:
        """Timestamp completion and use only application-owned public reasons."""
        return DependencyCheck(
            state=result.state,
            code=result.code,
            message=MESSAGES[result.code],
            checked_at=self.clock(),
        )

    async def _docker(self, host: str | None, request_id: str | None) -> DependencyCheck:
        """Ping only the chosen configured host and isolate its failure from model checks."""
        if host is None:
            return self._view(ProbeResult("not_checked", "host_not_selected"))
        try:
            async with asyncio.timeout(self.timeout):
                await self.runtime.ping(host)
        except TimeoutError:
            return self._view(ProbeResult("unavailable", "timeout"))
        except DockSightError as error:
            code = "timeout" if error.code == "runtime_timeout" else "runtime_unavailable"
            return self._view(ProbeResult("unavailable", code))
        except Exception as error:
            _log_failure(error, host, "docker", request_id)
            return self._view(ProbeResult("unavailable", "check_failed"))
        return self._view(ProbeResult("available", "ok"))

    async def _model(self, host: str | None, request_id: str | None) -> tuple[DependencyCheck, DependencyCheck]:
        """Keep unsupported metadata checks distinct from an unavailable model."""
        if self.probe is None:
            unknown = self._view(ProbeResult("not_checked", "probe_not_configured"))
            return unknown, unknown
        try:
            async with asyncio.timeout(self.timeout):
                provider, model = await self.probe.check()
        except TimeoutError:
            provider, model = ProbeResult("unavailable", "timeout"), ProbeResult("not_checked", "provider_unavailable")
        except Exception as error:
            _log_failure(error, host, "provider", request_id)
            provider, model = (
                ProbeResult("unavailable", "check_failed"),
                ProbeResult("not_checked", "provider_unavailable"),
            )
        return self._view(provider), self._view(model)

    async def check(self, host: str | None, request_id: str | None = None) -> SystemStatusView:
        """Reject unknown hosts before external work and collect bounded checks concurrently."""
        if host is not None and host not in {item.id for item in self.runtime.hosts()}:
            raise DockSightError("host_not_found", "Configured host not found", ErrorKind.NOT_FOUND)
        docker, model = await asyncio.gather(self._docker(host, request_id), self._model(host, request_id))
        return SystemStatusView(
            host=host,
            provider=self.provider,
            model=self.model,
            docker=docker,
            provider_check=model[0],
            model_check=model[1],
        )


def _log_failure(error: Exception, host: str | None, dependency: str, request_id: str | None) -> None:
    """Retain traceback locations and scope while excluding upstream exception text and payloads."""
    logging.getLogger("docksight.status").error(
        json.dumps(
            {
                "event": "system.check_failed",
                "host": host,
                "dependency": dependency,
                "request_id": request_id,
                "error_type": type(error).__name__,
                "stack": [
                    {"file": frame.filename, "line": frame.lineno, "function": frame.name}
                    for frame in traceback.extract_tb(error.__traceback__)
                ],
            }
        )
    )
