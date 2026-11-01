from unittest.mock import Mock

import pytest

from docksight.application.views.schemas import DiagnosisResponse
from tests.integration.live_e2e.cases import Case
from tests.integration.live_e2e.checks import _check_logs
from tests.integration.live_e2e.lab import OWNER_LABEL, ComposeLab


@pytest.mark.parametrize("owner", [None, "another-run"])
def test_graceful_setup_never_stops_a_foreign_container(owner: str | None) -> None:
    lab = object.__new__(ComposeLab)
    lab.owner = "own-run"
    row = Mock(labels={} if owner is None else {OWNER_LABEL: owner})
    with pytest.raises(RuntimeError, match="Refusing"):
        lab._prepare_shutdown({"clean-shutdown": row})
    row.stop.assert_not_called()
    row.exec_run.assert_not_called()


def test_graceful_setup_stops_only_the_ready_owned_workload() -> None:
    lab = object.__new__(ComposeLab)
    lab.owner = "own-run"
    row = Mock(labels={OWNER_LABEL: lab.owner})
    row.exec_run.return_value.exit_code = 0
    untouched = Mock()
    lab._prepare_shutdown({"clean-shutdown": row, "other": untouched})
    row.stop.assert_called_once_with(timeout=5)
    untouched.stop.assert_not_called()


def test_peer_validation_rejects_an_abnormal_exit_even_with_a_shutdown_log() -> None:
    lab = object.__new__(ComposeLab)
    lab.containers = {}
    row = Mock(attrs={"State": {"Status": "exited", "ExitCode": 1, "OOMKilled": False}})
    row.logs.return_value = b"LOG: database system is shut down\n"
    with pytest.raises(RuntimeError, match="failure"):
        lab._wait_ready({"clean-shutdown": row})


def test_slow_diagnosis_can_verify_collected_lines_older_than_the_latest_hundred_probes() -> None:
    lab = object.__new__(ComposeLab)
    lab.case = Case("unhealthy", ("unhealthy",), production_limits=True)
    history = ["HTTP server listening on 127.0.0.1:8080", *(f"probe={index} GET /health 503" for index in range(130))]
    row = Mock(id="worker")
    row.logs.side_effect = lambda tail: "\n".join(history[-tail:]).encode()
    lab.containers = {"unhealthy": row}
    answer = DiagnosisResponse.model_validate(
        {
            "summary": "The process is running but unhealthy.",
            "uncertain": True,
            "evidence": [
                {
                    "id": "e1",
                    "kind": "logs",
                    "host": "e2e",
                    "container_id": "worker",
                    "observed_at": "2026-10-31T10:00:00Z",
                    "data": {},
                }
            ],
            "widgets": [
                {
                    "widget_type": "log_anomalies",
                    "host": "e2e",
                    "container_id": "worker",
                    "evidence_ids": ["e1"],
                    "logs": {"entries": [{"message": history[0]}], "truncated": False},
                }
            ],
        }
    )
    _check_logs(answer, lab)
