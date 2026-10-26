from dataclasses import dataclass
from datetime import datetime
from typing import Literal

type ContainerState = Literal["created", "running", "paused", "restarting", "removing", "exited", "dead"]


@dataclass(frozen=True)
class Host:
    """Identify a configured Docker host without exposing connection credentials."""

    id: str
    name: str


@dataclass(frozen=True)
class ResourceMetrics:
    """Represent observed CPU and memory values, preserving unavailable measurements."""

    cpu_percent: float | None = None
    memory_usage_bytes: int | None = None
    memory_limit_bytes: int | None = None


@dataclass(frozen=True)
class ContainerSnapshot:
    """Capture allowlisted container state, sanitized metadata, and optional metrics."""

    host: str
    id: str
    name: str
    image: str
    state: ContainerState
    exit_code: int
    oom_killed: bool
    restart_count: int
    started_at: datetime | None
    observed_at: datetime
    metrics: ResourceMetrics = ResourceMetrics()
    environment: tuple[tuple[str, str], ...] = ()
    compose_project: str | None = None

    @property
    def fingerprint(self) -> str:
        """Identify lifecycle changes that invalidate a prepared mutation."""
        return f"{self.state}:{self.started_at}:{self.restart_count}"


@dataclass(frozen=True)
class LogEntry:
    """Pair a sanitized log message with its optional Docker timestamp."""

    message: str
    timestamp: datetime | None = None


@dataclass(frozen=True)
class LogBatch:
    """Return finite sanitized log entries and indicate omitted data."""

    entries: tuple[LogEntry, ...]
    truncated: bool = False


@dataclass(frozen=True)
class StackSummary:
    """Summarize observed Compose containers or desired and running Swarm tasks."""

    name: str
    kind: Literal["compose", "swarm"]
    total: int
    running: int
    container_ids: tuple[str, ...] = ()
