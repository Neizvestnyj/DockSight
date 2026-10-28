from dataclasses import dataclass
from typing import Literal, Protocol

type CheckState = Literal["available", "unavailable", "not_checked"]
type CheckCode = Literal[
    "ok",
    "host_not_selected",
    "timeout",
    "connection_failed",
    "runtime_unavailable",
    "credentials_rejected",
    "metadata_forbidden",
    "unsupported",
    "model_not_found",
    "model_not_listed",
    "rate_limited",
    "upstream_error",
    "invalid_response",
    "probe_not_configured",
    "check_failed",
    "provider_unavailable",
]


@dataclass(frozen=True)
class ProbeResult:
    """Return a safe availability result without upstream payloads or exception text."""

    state: CheckState
    code: CheckCode


class ModelStatusPort(Protocol):
    """Check provider and model metadata without invoking generation or loading a model."""

    async def check(self) -> tuple[ProbeResult, ProbeResult]:
        """Return independent provider reachability and model metadata outcomes."""
        ...
