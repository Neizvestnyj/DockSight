import os
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest
from docker.errors import DockerException

from tests.integration.live_e2e.lab import OWNER_LABEL, ROOT, ComposeLab, _compose, require_owner
from tests.integration.live_e2e.server import local_model_url, require_local_models


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434", "http://localhost:11434/", "http://[::1]:11434"])
def test_local_model_endpoint_accepts_only_explicit_loopback_locations(url: str) -> None:
    assert local_model_url(url) == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com",
        "http://127.0.0.1@api.example.com",
        "http://token@127.0.0.1:11434",
        "http://127.0.0.1:11434/api",
        "http://127.0.0.1:11434?key=value",
        "http://127.0.0.1:11434#fragment",
    ],
)
def test_local_model_endpoint_rejects_remote_or_credential_bearing_requests(url: str) -> None:
    with pytest.raises(ValueError):
        local_model_url(url)


def test_cleanup_requires_the_exact_run_owner() -> None:
    require_owner({OWNER_LABEL: "own-run"}, "own-run")
    with pytest.raises(RuntimeError, match="Refusing"):
        require_owner({OWNER_LABEL: "another-run"}, "own-run")
    with pytest.raises(RuntimeError, match="Refusing"):
        require_owner({}, "own-run")


@pytest.mark.parametrize("field", ["remote_model", "remote_host"])
def test_local_aliases_cannot_enable_cloud_generation(field: str) -> None:
    with pytest.raises(ValueError, match="Remote/cloud"):
        require_local_models([{"name": "local-alias", field: "upstream"}], ["local-alias"])


def test_missing_models_fail_preflight_instead_of_triggering_a_download() -> None:
    with pytest.raises(ValueError, match="not installed"):
        require_local_models([{"name": "installed"}], ["missing"])
    require_local_models([{"name": "installed"}], ["installed"])


def test_compose_fixture_is_resolved_independently_of_current_working_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(ROOT / "backend")
    assert (ROOT / "examples/live-e2e/compose.yaml").is_file()


def test_cleanup_continues_after_one_owned_resource_cannot_be_removed() -> None:
    lab = object.__new__(ComposeLab)
    lab.owner, lab.project = "own-run", "own-project"
    first = Mock(labels={OWNER_LABEL: "own-run"})
    second = Mock(labels={OWNER_LABEL: "own-run"})
    first.remove.side_effect = DockerException("Temporary removal failure")
    network = Mock(attrs={"Labels": {OWNER_LABEL: "own-run"}})
    lab.client = Mock()
    lab.client.containers.list.return_value = [first, second]
    lab.client.networks.list.return_value = [network]
    with pytest.raises(ExceptionGroup):
        lab.close()
    second.remove.assert_called_once_with(force=True, v=True)
    network.remove.assert_called_once()
    lab.client.close.assert_called_once()


@pytest.mark.parametrize(
    ("exit_code", "oom", "output"),
    [(137, True, b"out of memory"), (1, False, b"Permission denied while opening a data directory")],
)
def test_grafana_fixture_rejects_a_different_failure_cause(exit_code: int, oom: bool, output: bytes) -> None:
    lab = object.__new__(ComposeLab)
    row = Mock(attrs={"State": {"Status": "exited", "ExitCode": exit_code, "OOMKilled": oom}})
    row.logs.return_value = output
    lab.containers = {"grafana": row}
    with pytest.raises(RuntimeError, match="failure"):
        lab._wait_ready()


def test_timed_out_cli_is_terminated_before_fixture_cleanup_can_start() -> None:
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _compose([sys.executable, "-c", "import time; time.sleep(30)"], dict(os.environ), timeout=0.1)
    assert time.monotonic() - started < 5


def test_cleanup_never_deletes_a_foreign_resource_returned_by_the_sdk() -> None:
    lab = object.__new__(ComposeLab)
    lab.owner, lab.project = "own-run", "own-project"
    foreign = Mock(labels={OWNER_LABEL: "another-run"})
    own = Mock(labels={OWNER_LABEL: "own-run"})
    lab.client = Mock()
    lab.client.containers.list.return_value = [foreign, own]
    lab.client.networks.list.return_value = []
    with pytest.raises(ExceptionGroup):
        lab.close()
    foreign.remove.assert_not_called()
    own.remove.assert_called_once_with(force=True, v=True)
