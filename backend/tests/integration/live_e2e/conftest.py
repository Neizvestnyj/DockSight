from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from tests.integration.live_e2e.cases import CASES, FOLLOW_UP_CASES, FOLLOW_UP_SHUTDOWN_CASE, Case
from tests.integration.live_e2e.lab import ROOT, ComposeLab
from tests.integration.live_e2e.server import live_api, local_model_url, require_local_models


def pytest_addoption(parser: pytest.Parser) -> None:
    """Require explicit live execution and allow adding installed local models without code changes."""
    group = parser.getgroup("live-e2e")
    group.addoption("--live-e2e", action="store_true", help="Run real Docker and local Ollama diagnostics")
    group.addoption("--e2e-model", action="append", default=[], help="Installed Ollama model; repeat for a matrix")
    group.addoption("--e2e-model-url", default="http://127.0.0.1:11434", help="Loopback Ollama endpoint")
    group.addoption("--e2e-language", action="append", choices=["en", "ru"], help="Select a language; default both")
    group.addoption("--e2e-browser", action="store_true", help="Also run real Chrome group diagnostics")
    group.addoption(
        "--e2e-case",
        action="append",
        choices=[row.name for row in (*CASES, *FOLLOW_UP_CASES)],
        help="Select a scenario; repeat",
    )


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Collect the requested case/model cross product while leaving unrelated tests untouched."""
    function = metafunc.function.__name__
    if function not in {
        "test_live_diagnosis",
        "test_live_browser",
        "test_live_follow_up",
        "test_live_shutdown_group_follow_up",
    }:
        return
    names = metafunc.config.getoption("e2e_model") or ["disabled"]
    selected = metafunc.config.getoption("e2e_case")
    cases = _cases_for(function, selected)
    metafunc.parametrize("model_name", names)
    metafunc.parametrize("case", cases, ids=lambda row: row.name)
    metafunc.parametrize("language", metafunc.config.getoption("e2e_language") or ["en", "ru"])


def _cases_for(function: str, selected: list[str] | None) -> list[Case]:
    """Select follow-up fixtures separately from single-turn and browser scenarios."""
    if function == "test_live_follow_up":
        return [row for row in FOLLOW_UP_CASES if not selected or row.name in selected]
    if function == "test_live_shutdown_group_follow_up":
        return [FOLLOW_UP_SHUTDOWN_CASE] if not selected or FOLLOW_UP_SHUTDOWN_CASE.name in selected else []
    return _selected_cases(selected, function == "test_live_browser")


def _selected_cases(names: list[str] | None, browser: bool) -> list[Case]:
    """Restrict browser scenarios to group flows without changing HTTP scenario selection."""
    cases = [row for row in CASES if not names or row.name in names]
    return [row for row in cases if row.group and not row.typo] if browser else cases


@pytest.fixture(scope="session")
def model_endpoint(pytestconfig: pytest.Config) -> str:
    """Verify installed models before creating workloads; default collection performs no external I/O."""
    if not pytestconfig.getoption("live_e2e"):
        pytest.skip("Pass --live-e2e and --e2e-model to run real Docker/local model diagnostics")
    names: list[str] = pytestconfig.getoption("e2e_model")
    if not names:
        raise pytest.UsageError("Provide at least one --e2e-model; models are never downloaded automatically")
    try:
        url = local_model_url(pytestconfig.getoption("e2e_model_url"))
        response = httpx.get(url + "/api/tags", timeout=5, trust_env=False)
        response.raise_for_status()
        rows = response.json()["models"]
    except (ValueError, KeyError, httpx.HTTPError) as exc:
        raise pytest.UsageError(f"Local Ollama preflight failed ({type(exc).__name__})") from exc
    try:
        require_local_models(rows, names)
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc
    return url


@pytest.fixture
def lab(case: Case, model_endpoint: str) -> Iterator[ComposeLab]:
    """Always clean owned resources, including when Compose or readiness fails partway through setup."""
    fixture = ComposeLab(case)
    try:
        fixture.start()
        yield fixture
    finally:
        fixture.close()


@pytest.fixture
def api(
    lab: ComposeLab, model_name: str, model_endpoint: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[httpx.Client]:
    """Run a fresh HTTP application and real provider adapter without production settings or proxy routing."""
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1")
    with live_api(lab, model_name, model_endpoint) as client:
        yield client


@pytest.fixture(scope="session")
def artifacts(model_endpoint: str) -> Path:
    """Keep public responses and allowlisted fixture facts in an ignored per-run directory."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = ROOT / ".test-artifacts/live-e2e" / f"{stamp}-{uuid4().hex[:8]}"
    path.mkdir(parents=True)
    print(f"\nLive-e2e artifacts: {path}", flush=True)
    return path
