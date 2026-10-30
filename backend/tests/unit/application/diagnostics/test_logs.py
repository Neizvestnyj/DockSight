import json
from datetime import UTC, datetime

import pytest

from docksight.application.diagnostics.logs import fit_logs, log_data
from docksight.domain.runtime import LogBatch, LogEntry


@pytest.mark.parametrize("message", ["x" * 400, "Ж😀" * 200, '\\"' * 200], ids=["ascii", "unicode", "escaped"])
def test_json_budget_preserves_final_events_and_timestamps(message: str) -> None:
    observed = datetime(2026, 10, 27, 14, 2, 6, tzinfo=UTC)
    batch = LogBatch(
        (
            *(LogEntry(f"{index}: {message}", observed) for index in range(100)),
            LogEntry("received fast shutdown request", observed),
            LogEntry("database system is shut down", observed),
        )
    )
    fitted = fit_logs(batch, 256)
    assert [row.message for row in fitted.entries[-2:]] == [
        "received fast shutdown request",
        "database system is shut down",
    ]
    assert fitted.entries[-1].timestamp == observed
    assert fitted.truncated
    assert len(json.dumps(log_data(fitted), ensure_ascii=False).encode()) <= 256


def test_oversized_final_message_retains_a_sanitized_suffix_without_reordering_entries() -> None:
    batch = LogBatch((LogEntry("old"), LogEntry("x" * 10000 + "final marker")))
    fitted = fit_logs(batch, 256)
    assert len(fitted.entries) == 1
    assert fitted.entries[0].message.endswith("final marker")
    assert fitted.truncated
