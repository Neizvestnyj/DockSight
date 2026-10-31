import json
import os
import shutil
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from tests.integration.live_e2e.cases import Case, Language
from tests.integration.live_e2e.checks import check_answer, check_selection
from tests.integration.live_e2e.lab import ROOT, ComposeLab, run_command
from tests.integration.live_e2e.reports import record_run, report_path
from tests.integration.live_e2e.server import live_api

pytestmark = [pytest.mark.live, pytest.mark.docker]


@pytest.fixture(scope="session")
def browser_ready(pytestconfig: pytest.Config) -> str:
    """Skip browser I/O unless requested and fail before Docker setup when its prerequisites are missing."""
    if not pytestconfig.getoption("live_e2e") or not pytestconfig.getoption("e2e_browser"):
        pytest.skip("Pass --live-e2e --e2e-browser to exercise the real browser and local model")
    node = shutil.which("node")
    required = (ROOT / "frontend/dist/index.html", ROOT / "frontend/node_modules/@playwright/test/cli.js")
    if not node or not all(path.is_file() for path in required):
        raise pytest.UsageError("Install Node/frontend dependencies and run npm --prefix frontend run build first")
    return node


def test_live_browser(
    browser_ready: str,
    lab: ComposeLab,
    case: Case,
    language: Language,
    model_name: str,
    model_endpoint: str,
    artifacts: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive Chrome without mocked routes and apply the same exact-resource checks to its real SSE response."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1")
    target = report_path(artifacts, model_name, case, language, "browser")
    started = datetime.now(UTC).isoformat()
    payload: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    clarification_events: list[dict[str, Any]] = []
    with live_api(lab, model_name, model_endpoint, (f"http://127.0.0.1:{port}",)) as api:
        token = SecretStr(api.headers["Authorization"].removeprefix("Bearer "))
        options = {
            "DOCKSIGHT_E2E_PREVIEW_PORT": str(port),
            "DOCKSIGHT_E2E_API": str(api.base_url).rstrip("/"),
            "DOCKSIGHT_E2E_BROWSER_INPUT": json.dumps(
                {
                    "project": lab.project,
                    "explicit": case.explicit,
                    "clarify": case.needs_selection,
                    "peer_project": lab.peer_project,
                    "language": language,
                    "query": case.query(lab.project, "", language),
                    "output": str(target),
                }
            ),
        }
        try:
            _run_browser(browser_ready, options, token)
            recorded = json.loads(target.read_text(encoding="utf-8"))
            payload, events = recorded["input"], recorded["events"]
            clarification_events = recorded.get("clarification_events", [])
            if case.needs_selection:
                check_selection(clarification_events, lab)
            check_answer(events, lab, case, language)
        finally:
            if target.is_file():
                recorded = json.loads(target.read_text(encoding="utf-8"))
                payload, events = recorded.get("input") or {}, recorded["events"]
                clarification_events = recorded.get("clarification_events", [])
            record_run(target, lab, model_name, started, payload, events, clarification_events)


def _run_browser(node: str, options: dict[str, str], token: SecretStr) -> None:
    """Bound the owned Playwright/preview process tree and redact credentials from diagnostic failures."""
    environment = {
        **os.environ,
        **options,
        "DOCKSIGHT_E2E_TOKEN": token.get_secret_value(),
        "PLAYWRIGHT_NO_COPY_PROMPT": "1",
    }
    try:
        run_command(
            [
                node,
                str(ROOT / "frontend/node_modules/@playwright/test/cli.js"),
                "test",
                "--config",
                str(ROOT / "frontend/playwright.live.config.ts"),
            ],
            environment,
            timeout=360,
            label="Live browser",
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise RuntimeError(str(exc).replace(token.get_secret_value(), "[REDACTED]")) from None
