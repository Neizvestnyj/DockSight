import json
from dataclasses import replace
from typing import Final, cast

from pydantic import TypeAdapter

from docksight.domain.diagnostics import JsonObject
from docksight.domain.runtime import LogBatch, LogEntry

_LOGS: Final = TypeAdapter(LogBatch)


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
