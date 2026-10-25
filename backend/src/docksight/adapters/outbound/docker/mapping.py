import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from docksight.application.redaction import Redactor, secret_name
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import (
    ContainerSnapshot,
    ContainerState,
    LogBatch,
    LogEntry,
    ResourceMetrics,
)


def parse_time(value: str) -> datetime | None:
    """Parse Docker timestamps as UTC and discard missing or invalid values."""
    if not value or value.startswith("0001-"):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def map_container(
    raw: Mapping[str, Any],
    host: str,
    env_allowlist: tuple[str, ...],
    redactor: Redactor,
) -> ContainerSnapshot:
    """Allowlist inspect fields and redact names, images, labels, and environment values."""
    config: dict[str, Any] = raw.get("Config") or {}
    state: dict[str, Any] = raw.get("State") or {}
    labels: dict[str, str] = config.get("Labels") or {}
    raw_environment: list[str] = config.get("Env") or []
    status = state.get("Status")
    if status not in {"created", "running", "paused", "restarting", "removing", "exited", "dead"}:
        raise DockSightError("invalid_runtime_data", "Unknown container state", 502)
    clean = redactor.with_environment(raw_environment)
    environment = tuple(
        (key, clean.text(value))
        for entry in raw_environment
        for key, _, value in [entry.partition("=")]
        if key in env_allowlist and not secret_name(key)
    )

    return ContainerSnapshot(
        host=host,
        id=raw["Id"],
        name=clean.text(raw["Name"].lstrip("/")),
        image=clean.text(config.get("Image", "")),
        state=cast(ContainerState, status),
        exit_code=int(state.get("ExitCode", 0)),
        oom_killed=bool(state.get("OOMKilled", False)),
        restart_count=int(raw.get("RestartCount", 0)),
        started_at=parse_time(state.get("StartedAt", "")),
        observed_at=datetime.now(UTC),
        environment=environment,
        compose_project=clean.text(labels.get("com.docker.compose.project", "")) or None,
    )


def _cpu_percent(raw: Mapping[str, Any]) -> float | None:
    """Calculate Docker CPU usage from two valid monotonic samples."""
    cpu: dict[str, Any] = raw.get("cpu_stats") or {}
    previous: dict[str, Any] = raw.get("precpu_stats") or {}
    usage_now: dict[str, Any] = cpu.get("cpu_usage") or {}
    usage_previous: dict[str, Any] = previous.get("cpu_usage") or {}
    current_total = usage_now.get("total_usage")
    previous_total = usage_previous.get("total_usage")
    system = cpu.get("system_cpu_usage")
    previous_system = previous.get("system_cpu_usage")
    if (
        not isinstance(current_total, (int, float))
        or not isinstance(previous_total, (int, float))
        or not isinstance(system, (int, float))
        or not isinstance(previous_system, (int, float))
    ):
        return None
    delta = system - previous_system
    if delta <= 0 or current_total < previous_total:
        return None
    count = cpu.get("online_cpus") or len(usage_now.get("percpu_usage", [])) or 1
    value = (current_total - previous_total) / delta * count * 100

    return round(value, 2) if math.isfinite(value) else None


def map_metrics(raw: Mapping[str, Any]) -> ResourceMetrics:
    """Map CPU and cache-adjusted memory counters into the runtime contract."""
    memory: dict[str, Any] = raw.get("memory_stats") or {}
    usage = memory.get("usage")
    if isinstance(usage, int):
        stats: dict[str, Any] = memory.get("stats") or {}
        usage = max(0, usage - stats.get("inactive_file", stats.get("total_inactive_file", 0)))

    return ResourceMetrics(_cpu_percent(raw), usage, memory.get("limit"))


def parse_logs(raw: bytes, redactor: Redactor, max_bytes: int, lines: int) -> LogBatch:
    """Redact bounded log lines and discard a partial line at the input cutoff."""
    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]
        raw = raw[: raw.rfind(b"\n") + 1]
    text = redactor.text(raw.decode("utf-8", errors="replace"))
    encoded = text.encode()
    truncated = truncated or len(encoded) > max_bytes
    text = encoded[:max_bytes].decode("utf-8", errors="ignore")
    rows = text.splitlines()
    truncated = truncated or len(rows) > lines
    entries: list[LogEntry] = []
    for row in rows[:lines]:
        prefix, _, message = row.partition(" ")
        timestamp = parse_time(prefix) if prefix[:4].isdigit() and "T" in prefix else None
        entries.append(LogEntry(message if timestamp else row, timestamp))

    return LogBatch(tuple(entries), truncated)
