import json
from dataclasses import replace
from typing import Final, cast

from pydantic import TypeAdapter

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.ports.runtime import RuntimeReadPort
from docksight.application.views.schemas import GroupLogResult
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import ContainerSnapshot, LogBatch, LogEntry

_LOGS: Final = TypeAdapter(LogBatch)
_SNAPSHOT: Final = TypeAdapter(ContainerSnapshot)


def needs_logs(snapshot: ContainerSnapshot) -> bool:
    """Identify observations needing inspection without treating startup checks as failures."""
    return (
        snapshot.state != "running"
        or snapshot.oom_killed
        or snapshot.restart_count > 0
        or snapshot.health == "unhealthy"
    )


async def collect_logs(
    runtime: RuntimeReadPort, context: EvidenceContext, snapshot: ContainerSnapshot, log_lines: int, log_bytes: int
) -> GroupLogResult:
    """Keep an observed snapshot when its bounded log read fails, preserving exact-resource provenance."""
    result = GroupLogResult(container_id=snapshot.id, name=snapshot.name, state="failed")
    try:
        context.record(
            "container", snapshot.host, cast(JsonObject, _SNAPSHOT.dump_python(snapshot, mode="json")), snapshot
        )
        batch = await runtime.logs(snapshot.host, snapshot.id, min(log_lines, 200), min(log_bytes, 4096))
        batch = fit_logs(batch, min(context.remaining_bytes, 8192))
        ref = context.record("logs", snapshot.host, log_data(batch), snapshot, batch)
    except DockSightError as exc:
        result.code = exc.code
        return result
    result.state = "collected"
    result.evidence_id = ref.id
    return result


def log_data(logs: LogBatch) -> JsonObject:
    """Serialize sanitized log evidence using the same representation as its byte budget."""
    return cast(JsonObject, _LOGS.dump_python(logs, mode="json"))


def _log_suffix(logs: LogBatch, characters: int) -> LogBatch:
    """Keep the latest sanitized messages in original order, counting empty entries toward the bound."""
    entries: list[LogEntry] = []
    for entry in reversed(logs.entries):
        if characters <= 0:
            break
        size = min(len(entry.message), characters - 1)
        if not size and entry.message:
            break
        entries.append(replace(entry, message=entry.message[-size:] if size else ""))
        characters -= len(entry.message) + 1
    return LogBatch(tuple(reversed(entries)), truncated=True)


def fit_logs(logs: LogBatch, budget: int) -> LogBatch:
    """Fit the latest log content to the remaining JSON bytes, including escaping and metadata."""
    if len(json.dumps(log_data(logs), ensure_ascii=False).encode()) <= budget:
        return logs
    low, high = 0, sum(len(entry.message) + 1 for entry in logs.entries)
    while low < high:
        middle = (low + high + 1) // 2
        candidate = _log_suffix(logs, middle)
        if len(json.dumps(log_data(candidate), ensure_ascii=False).encode()) <= budget:
            low = middle
        else:
            high = middle - 1
    return _log_suffix(logs, low)
