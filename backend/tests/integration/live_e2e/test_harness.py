import os
import secrets
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest
from docker.errors import DockerException
from pydantic import SecretStr

from docksight.application.views.schemas import DiagnosisResponse
from docksight.bootstrap import Settings
from tests.integration.live_e2e.cases import CASES, Case
from tests.integration.live_e2e.checks import check_language, check_narrative, check_selection
from tests.integration.live_e2e.lab import OWNER_LABEL, ROOT, ComposeLab, require_owner, run_command
from tests.integration.live_e2e.server import live_api, local_model_url, require_local_models
from tests.integration.live_e2e.test_browser import _run_browser


def test_bare_host_case_does_not_request_the_choice_required_for_named_ambiguity() -> None:
    cases = {row.spelling: row for row in CASES if row.spelling in {"unscoped", "ambiguous"}}
    assert not cases["unscoped"].needs_selection
    assert cases["ambiguous"].needs_selection
    assert cases["unscoped"].query("infra", "", "en") == "What happened?"
    assert cases["unscoped"].query("infra", "", "ru") == "Что случилось?"


@pytest.mark.parametrize(
    ("name", "limits"),
    [("compose-unscoped", (200, 65536)), ("compose-chat", (30, 2048)), ("clean-shutdown", (200, 65536))],
)
def test_dense_host_case_uses_production_log_limits_without_changing_other_cases(
    name: str, limits: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    lab = object.__new__(ComposeLab)
    lab.owner = "settings-test"
    lab.case = next(row for row in CASES if row.name == name)
    captured: list[Settings] = []

    def capture(settings: Settings, **ports: object) -> None:
        """Stop before starting HTTP or model clients while retaining the actual configured budgets."""
        captured.append(settings)
        raise RuntimeError("Captured settings")

    monkeypatch.setattr("tests.integration.live_e2e.server.FixtureRuntime", lambda lab: Mock())
    monkeypatch.setattr("tests.integration.live_e2e.server.build_components", capture)
    with pytest.raises(RuntimeError, match="Captured settings"), live_api(lab, "fixture-model", "http://127.0.0.1"):
        pytest.fail("The settings probe must stop before serving an API")
    assert (captured[0].log_lines, captured[0].log_bytes) == limits


@pytest.mark.parametrize("violation", ["invented", "missing", "answer", "read", "failure"])
def test_clarification_checks_reject_invented_missing_or_prematurely_inspected_scope(violation: str) -> None:
    lab = object.__new__(ComposeLab)
    lab.project, lab.peer_project = "infra-a", "infra-b"
    candidates = [{"kind": "compose", "name": name} for name in (lab.project, lab.peer_project)]
    events = [
        {"type": "turn.started"},
        {"type": "clarification.required", "selection": {"candidates": candidates}},
        {"type": "turn.completed"},
    ]
    check_selection(events, lab)
    if violation == "invented":
        candidates[1]["name"] = "invented"
    elif violation == "missing":
        candidates.pop()
    else:
        injected = {
            "answer": {"type": "answer.ready"},
            "read": {"type": "tool.started", "tool": "get_container_logs"},
            "failure": {"type": "turn.failed"},
        }[violation]
        events.insert(1, injected)
    with pytest.raises(AssertionError):
        check_selection(events, lab)


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("The database connection failed during startup.", "ru"),
        ("Контейнер завершился из-за ошибки подключения к базе данных.", "en"),
        ("backend-1 e1 137 OOM", "ru"),
        ("`Контейнер завершился`", "ru"),
    ],
)
def test_language_check_rejects_wrong_language_and_evidence_without_prose(text: str, language: str) -> None:
    with pytest.raises(AssertionError, match="language"):
        check_language(text, language, ("backend-1",))


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Невозможно подключиться к PostgreSQL в backend-1. Логи: `Connection refused`.", "ru"),
        ("The database is unavailable. Docker logs: `Ошибка подключения`.", "en"),
        ("Контейнер завершился.\n```log\n" + "Connection refused\n" * 50 + "```", "ru"),
        ("Неверный Chat ID в Telegram.", "ru"),
        ("Отсутствует Telegram receiver.", "ru"),
        ("Нет Chat ID.", "ru"),
        ("No Chat ID.", "en"),
    ],
)
def test_language_check_excludes_verbatim_code_and_resource_identifiers(text: str, language: str) -> None:
    check_language(text, language, ("backend-1",))


@pytest.mark.parametrize("field", ["immediate", "underlying", "unknowns"])
def test_russian_summary_cannot_hide_an_english_cause_or_unknown_detail(field: str) -> None:
    cause = {
        "immediate": "Произошла ошибка подключения к базе данных.",
        "underlying": "Настройки сети требуют проверки.",
        "unknowns": ["Причина недоступности пока неизвестна."],
        "evidence_ids": ["e1"],
    }
    cause[field] = ["The database is unreachable."] if field == "unknowns" else "The database is unreachable."
    answer = DiagnosisResponse.model_validate(
        {
            "summary": "Контейнер завершился из-за ошибки подключения к базе данных.",
            "uncertain": True,
            "cause": cause,
            "widgets": [],
            "evidence": [],
        }
    )
    with pytest.raises(AssertionError, match="language"):
        check_narrative(answer, "ru", ())


@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize("quoted", [False, True])
def test_language_check_preserves_observed_logs_without_requiring_their_translation(
    language: str, quoted: bool
) -> None:
    message = "Worker ended without recording the reason for termination"
    observed = f"'{message}'" if quoted else message
    answer = DiagnosisResponse.model_validate(
        {
            "summary": "Контейнер завершился. Причина пока неизвестна." if language == "ru" else "The worker exited.",
            "uncertain": True,
            "cause": {
                "immediate": f"Ошибка запуска: {observed}." if language == "ru" else message,
                "unknowns": [f"Точная причина в логах не указана однозначно (только фраза '{message}')."]
                if language == "ru"
                else ["The underlying cause remains unknown."],
                "evidence_ids": ["e1"],
            },
            "evidence": [],
            "widgets": [
                {
                    "widget_type": "log_anomalies",
                    "host": "e2e",
                    "container_id": "worker",
                    "evidence_ids": ["e1"],
                    "logs": {"entries": [{"timestamp": None, "message": message}], "truncated": False},
                }
            ],
        }
    )
    check_narrative(answer, language, ())


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


def test_peer_compose_setup_rejects_an_existing_namespace_before_calling_the_cli() -> None:
    lab = object.__new__(ComposeLab)
    lab.client = Mock()
    lab.client.containers.list.return_value = [Mock()]
    with pytest.raises(RuntimeError, match="reuse"):
        lab._compose("existing-peer", ("backend",))
    lab.client.containers.list.assert_called_once_with(
        all=True,
        filters={"label": "com.docker.compose.project=existing-peer"},
    )


def test_small_unscoped_fixture_keeps_the_exact_requested_primary_service_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = object.__new__(ComposeLab)
    lab.project = "small-host"
    lab.case = Case("small-host", ("backend",), group=True, spelling="unscoped")
    row = Mock(labels={"com.docker.compose.service": "backend"})
    for name in ("_compose", "_wait_ready", "_start_peer", "_start_standalone"):
        monkeypatch.setattr(lab, name, Mock())
    monkeypatch.setattr(lab, "_owned_containers", lambda: [row])
    lab.start()
    assert lab.containers == {"backend": row}


@pytest.mark.parametrize("services", [("backend",), ("backend", "nginx")])
def test_unscoped_fixture_scales_nginx_only_when_it_is_selected(
    services: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    lab = object.__new__(ComposeLab)
    lab.owner, lab.project = "own-run", "host-project"
    lab.case = Case("host-fixture", services, group=True, spelling="unscoped")
    lab.client = Mock()
    lab.client.containers.list.return_value = []
    calls: list[list[str]] = []

    def capture(arguments: list[str], environment: dict[str, str]) -> None:
        """Retain the actual CLI boundary without starting Docker workloads."""
        calls.append(arguments)

    monkeypatch.setattr("tests.integration.live_e2e.lab.run_command", capture)
    lab._compose(lab.project, services)
    assert ("--scale" in calls[0]) is ("nginx" in services)


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


def test_clean_shutdown_fixture_rejects_an_abnormal_exit_even_with_a_shutdown_log() -> None:
    lab = object.__new__(ComposeLab)
    row = Mock(attrs={"State": {"Status": "exited", "ExitCode": 1, "OOMKilled": False}})
    row.logs.return_value = b"LOG: database system is shut down\n"
    lab.containers = {"database-stopped": row}
    with pytest.raises(RuntimeError, match="failure"):
        lab._wait_ready()


def test_timed_out_cli_is_terminated_before_fixture_cleanup_can_start() -> None:
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_command([sys.executable, "-c", "import time; time.sleep(30)"], dict(os.environ), timeout=0.1)
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


def test_browser_failure_redacts_credentials_in_both_message_and_pytest_argument_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = SecretStr(secrets.token_urlsafe(32))

    def fail_cli(arguments: list[str], environment: dict[str, str], **options: object) -> None:
        """Inject a tool failure containing its environment credential at the external process boundary."""
        raise RuntimeError(f"CLI failed with {environment['DOCKSIGHT_E2E_TOKEN']}")

    monkeypatch.setattr("tests.integration.live_e2e.test_browser.run_command", fail_cli)
    with pytest.raises(RuntimeError, match="REDACTED") as failure:
        _run_browser("node", {}, secret)
    report = str(failure.getrepr(showlocals=False, funcargs=True))
    assert secret.get_secret_value() not in report
