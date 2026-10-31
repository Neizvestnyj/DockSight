import runpy
from collections.abc import Callable
from typing import cast

import pytest

from docksight.adapters.outbound.docker.mapping import parse_logs
from docksight.application.redaction import Redactor
from tests.integration.live_e2e.lab import ROOT


@pytest.mark.parametrize("dense", [False, True])
def test_opt_in_startup_history_fills_one_bounded_automatic_log_read(
    dense: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    namespace = runpy.run_path(str(ROOT / "examples/live-e2e/workload.py"))
    emit = cast(Callable[[], None], namespace["startup_history"])
    monkeypatch.setenv("DOCKSIGHT_E2E_DENSE_LOGS", "1" if dense else "0")
    emit()
    output = capsys.readouterr().out
    if not dense:
        assert output == ""
        return
    assert 4096 < len(output.encode()) < 10000
    assert "trace_id=" in output and "2026-10-31T" in output
    timestamp = "2026-10-31T10:12:59Z"
    raw = "".join(f"{timestamp} {line}\n" for line in output.splitlines()).encode()
    batch = parse_logs(raw, Redactor(), 4096, 200)
    assert batch.truncated
    retained_bytes = sum(len(timestamp) + len(row.message.encode()) + 2 for row in batch.entries)
    assert 3800 <= retained_bytes <= 4096
