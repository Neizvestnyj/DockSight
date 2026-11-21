import asyncio
from datetime import UTC, datetime

import pytest

from docksight.application.ports.status import ProbeResult
from docksight.application.system_status import SystemStatus
from docksight.domain.errors import DockSightError, ErrorKind
from tests.fakes import FakeRuntime


class Probe:
    """Return deterministic metadata checks without a model generation method."""

    def __init__(self, code: str = "ok") -> None:
        """Select a safe metadata outcome and count invocations."""
        self.code = code
        self.calls = 0

    async def check(self) -> tuple[ProbeResult, ProbeResult]:
        """Keep provider reachability independent of model metadata support."""
        self.calls += 1
        return ProbeResult("available", "ok"), ProbeResult("not_checked", self.code)


async def test_checks_preserve_separate_results_and_reject_unknown_hosts() -> None:
    runtime = FakeRuntime()
    probe = Probe("unsupported")
    now = datetime(2026, 10, 27, tzinfo=UTC)
    status = SystemStatus(runtime, probe, "compatible", "configured-model", clock=lambda: now)
    result = await status.check("local")
    assert result.docker.state == "available"
    assert result.provider_check.state == "available"
    assert result.model_check.state == "not_checked"
    assert result.model_check.code == "unsupported"
    assert result.docker.checked_at == now
    with pytest.raises(DockSightError, match="Configured host not found"):
        await status.check("unknown")
    assert probe.calls == 1


async def test_docker_timeout_does_not_hide_available_model_metadata() -> None:
    class SlowRuntime(FakeRuntime):
        """Simulate a Docker connection that exceeds its status deadline."""

        async def ping(self, host: str) -> None:
            """Suspend until the application cancels this read."""
            await asyncio.sleep(60)

    result = await SystemStatus(SlowRuntime(), Probe(), "ollama", "model", timeout=0.01).check("local")
    assert result.docker.state == "unavailable"
    assert result.docker.code == "timeout"
    assert result.provider_check.state == "available"


async def test_unexpected_failures_are_safe_and_unselected_host_is_not_probed() -> None:
    class BrokenProbe(Probe):
        """Fail with a private upstream URL that must not enter the response."""

        async def check(self) -> tuple[ProbeResult, ProbeResult]:
            """Exercise the final failure boundary without forwarding exception text."""
            raise RuntimeError("http://private-provider secret-sentinel")

    result = await SystemStatus(FakeRuntime(), BrokenProbe(), "ollama", "model").check(None)
    assert result.docker.state == "not_checked"
    assert result.docker.code == "host_not_selected"
    assert result.provider_check.state == "unavailable"
    assert result.model_check.state == "not_checked"
    assert "secret-sentinel" not in result.model_dump_json()
    assert "private-provider" not in result.model_dump_json()


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (DockSightError("runtime_timeout", "private-sentinel", ErrorKind.TIMEOUT), "timeout"),
        (DockSightError("runtime_unavailable", "private-sentinel", ErrorKind.UNAVAILABLE), "runtime_unavailable"),
        (RuntimeError("private-sentinel"), "check_failed"),
    ],
)
async def test_docker_status_keeps_safe_failure_codes_and_independent_model_status(
    failure: Exception, expected_code: str, caplog: pytest.LogCaptureFixture
) -> None:
    class BrokenRuntime(FakeRuntime):
        """Raise a controlled transport error during the Docker probe."""

        async def ping(self, host: str) -> None:
            """Fail with private detail that must not be logged or shown to clients."""
            raise failure

    result = await SystemStatus(BrokenRuntime(), Probe(), "ollama", "model").check("local", "status-request")
    assert (result.docker.state, result.docker.code) == ("unavailable", expected_code)
    assert result.provider_check.state == "available"
    assert "private-sentinel" not in result.model_dump_json()
    assert "private-sentinel" not in caplog.text
    if expected_code == "check_failed":
        assert "status-request" in caplog.text


async def test_provider_timeout_keeps_docker_available_and_model_unchecked() -> None:
    class TimedOutProbe(Probe):
        """Represent metadata failure at its own deadline."""

        async def check(self) -> tuple[ProbeResult, ProbeResult]:
            """Raise the timeout exposed by a bounded provider probe."""
            raise TimeoutError

    result = await SystemStatus(FakeRuntime(), TimedOutProbe(), "ollama", "model").check("local")
    assert result.docker.state == "available"
    assert (result.provider_check.state, result.provider_check.code) == ("unavailable", "timeout")
    assert (result.model_check.state, result.model_check.code) == ("not_checked", "provider_unavailable")
