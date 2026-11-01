import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from docksight.application.views.schemas import (
    ActionRecommendation,
    ActionView,
    CauseAssessment,
    ContainerStatusCard,
    DiagnosisResponse,
    LogAnomalyCard,
)
from docksight.domain.actions import ActionState
from docksight.domain.runtime import ContainerSnapshot, LogBatch, LogEntry
from tests.integration.live_e2e.causal_checks import CausalProfile, check_causality


class NarrativeExample(BaseModel):
    """Load independently authored expectations without deriving labels from the oracle."""

    model_config = ConfigDict(extra="forbid")
    profile: CausalProfile
    field: Literal["summary", "cause.immediate", "cause.underlying", "cause.unknowns", "recommendation"]
    text: str
    valid: bool
    reason: str
    log: str | None = None
    isolated_unknowns: bool = False
    relationship_unknown: bool = False


def _examples() -> list[NarrativeExample]:
    """Read the bilingual positive and negative corpus as explicit typed test cases."""
    path = Path(__file__).with_name("fixtures") / "causal_narratives.json"
    return [NarrativeExample.model_validate(row) for row in json.loads(path.read_text(encoding="utf-8"))]


def _answer(profile: CausalProfile) -> DiagnosisResponse:
    """Build a valid single-target narrative whose one field each corpus example can replace."""
    immediate = {
        "clean_shutdown": "Orderly shutdown with exit 0; its initiator is unknown.",
        "unknown_exit": "Exit 137 is observed; its cause is unknown and OOM is not established.",
        "oom": "Docker confirms an OOM kill.",
        "running_unhealthy": "The process is running but its health check is unhealthy; the reason is unknown.",
        "running_history": "The process is running with historical SQL errors.",
    }[profile]
    unknown = {
        "clean_shutdown": "The shutdown initiator is unknown.",
        "unknown_exit": "The exit reason is unknown.",
        "oom": "The allocation responsible is unknown.",
        "running_unhealthy": "The reason for the failed health check is unknown.",
        "running_history": "The origin of the invalid SQL data is unknown.",
    }[profile]
    now = datetime.now(UTC)
    snapshot = ContainerSnapshot(
        host="fixture-host",
        id="a" * 64,
        name="worker",
        image="fixture:local",
        state="running" if profile.startswith("running_") else "exited",
        exit_code=137 if profile in {"unknown_exit", "oom"} else 0,
        oom_killed=profile == "oom",
        restart_count=0,
        started_at=now,
        observed_at=now,
        health="unhealthy" if profile == "running_unhealthy" else None,
    )
    action = ActionView(
        id="fixture-action",
        host=snapshot.host,
        container_id=snapshot.id,
        operation="restart",
        expires_at=now + timedelta(minutes=1),
        state=ActionState.PREPARED,
        message="Confirm restart of worker.",
    )
    return DiagnosisResponse(
        summary=immediate,
        uncertain=True,
        cause=CauseAssessment(
            immediate=immediate,
            unknowns=[unknown],
            evidence_ids=["e1"],
        ),
        evidence=[],
        widgets=[ContainerStatusCard(snapshot=snapshot, evidence_ids=["e1"], actions=[action])],
    )


def _replace_field(answer: DiagnosisResponse, example: NarrativeExample) -> None:
    """Put each authored sentence into its displayed narrative location without altering its label."""
    assert answer.cause is not None
    if example.isolated_unknowns:
        answer.summary = answer.cause.immediate = "The status card reports the observed runtime state."
        answer.cause.unknowns = []
    if example.field == "summary":
        answer.summary = example.text
    elif example.field == "cause.immediate":
        answer.cause.immediate = example.text
    elif example.field == "cause.underlying":
        answer.cause.underlying = example.text
    elif example.field == "cause.unknowns":
        answer.cause.unknowns.append(example.text)
    else:
        card = answer.widgets[0]
        assert isinstance(card, ContainerStatusCard)
        card.recommendation = ActionRecommendation(action_id="fixture-action", reason=example.text)
    if example.log:
        answer.widgets.append(
            LogAnomalyCard(
                host="fixture-host",
                container_id="a" * 64,
                logs=LogBatch(entries=(LogEntry(example.log),)),
                evidence_ids=["e2"],
            )
        )


@pytest.mark.parametrize("example", _examples(), ids=lambda row: f"{row.profile}-{row.field}-{row.reason}")
def test_authored_narrative_matches_observed_causality(example: NarrativeExample) -> None:
    answer = _answer(example.profile)
    _replace_field(answer, example)
    if example.valid:
        check_causality(answer, example.profile, relationship_unknown=example.relationship_unknown)
    else:
        with pytest.raises(AssertionError):
            check_causality(answer, example.profile, relationship_unknown=example.relationship_unknown)


@pytest.mark.parametrize("profile", ["clean_shutdown", "unknown_exit", "running_unhealthy"])
def test_unknown_fixture_cause_requires_explicit_uncertainty(profile: CausalProfile) -> None:
    answer = _answer(profile)
    answer.uncertain = False
    assert answer.cause
    answer.cause.unknowns = []
    answer.summary = answer.cause.immediate = "The observed state explains the whole incident."
    with pytest.raises(AssertionError):
        check_causality(answer, profile)


def test_confirmed_oom_must_be_recognized_in_model_narrative() -> None:
    answer = _answer("oom")
    answer.summary = "Worker exited with code 137."
    assert answer.cause
    answer.cause.immediate = "The container exited."
    with pytest.raises(AssertionError):
        check_causality(answer, "oom")


def test_raw_log_observations_do_not_count_as_model_claims() -> None:
    answer = _answer("running_history")
    answer.widgets.append(
        LogAnomalyCard(
            host="fixture-host",
            container_id="a" * 64,
            logs=LogBatch(entries=(LogEntry("Worker crashed because the service is healthy."),)),
            evidence_ids=["e2"],
        )
    )
    check_causality(answer, "running_history")


def test_sql_uncertainty_does_not_replace_unknown_shutdown_initiator() -> None:
    answer = _answer("clean_shutdown")
    answer.summary = "The container exited with code 0 after repeated database errors."
    assert answer.cause
    answer.cause.immediate = "An orderly shutdown was observed."
    answer.cause.unknowns = ["The origin of the invalid SQL data is unknown."]
    with pytest.raises(AssertionError):
        check_causality(answer, "clean_shutdown")


@pytest.mark.parametrize(
    "unknown",
    ["The reason for process termination is unknown.", "Причина завершения работы процесса неизвестна."],
)
def test_clean_shutdown_accepts_explicit_unknown_termination_reason_without_other_uncertainty(unknown: str) -> None:
    answer = _answer("clean_shutdown")
    assert answer.cause
    answer.summary = answer.cause.immediate = "Docker reports exit 0."
    answer.cause.unknowns = [unknown]
    check_causality(answer, "clean_shutdown")


@pytest.mark.parametrize(
    "unknown",
    [
        "The database errors occurred before shutdown but do not establish why the process was stopped.",
        "The specific process or signal that initiated the shutdown is not observed in the logs.",
        "Логи не позволяют установить, почему процесс завершился.",
    ],
)
def test_unknowns_can_explicitly_disclaim_an_unestablished_stop_cause(unknown: str) -> None:
    answer = _answer("clean_shutdown")
    assert answer.cause
    answer.summary = answer.cause.immediate = "Docker reports exit 0."
    answer.cause.unknowns = [unknown]
    check_causality(answer, "clean_shutdown")


@pytest.mark.parametrize("contrast", ["rather than", "instead of"])
def test_clean_shutdown_contrasted_with_a_crash_is_not_an_asserted_crash(contrast: str) -> None:
    answer = _answer("clean_shutdown")
    answer.summary = f"The container exited with code 0, which indicates an orderly shutdown {contrast} a crash."
    check_causality(answer, "clean_shutdown")
    answer.summary = f"{contrast.capitalize()} waiting, the container crashed."
    with pytest.raises(AssertionError):
        check_causality(answer, "clean_shutdown")


def test_russian_memory_overflow_kill_is_an_oom_event_and_not_an_unexplained_exit() -> None:
    text = "Контейнер был убит по причине переполнения памяти (OOM)."
    answer = _answer("oom")
    assert answer.cause
    answer.summary = answer.cause.immediate = text
    check_causality(answer, "oom")
    unknown = _answer("unknown_exit")
    unknown.summary = text
    with pytest.raises(AssertionError):
        check_causality(unknown, "unknown_exit")


@pytest.mark.parametrize(
    "unknown",
    [
        "The reason for the failed health check is not yet established.",
        "The cause of the failed health check (e.g., unavailable dependency or misconfiguration) is unknown.",
    ],
)
def test_unresolved_probe_causes_survive_qualifiers_and_abbreviated_examples(unknown: str) -> None:
    answer = _answer("running_unhealthy")
    assert answer.cause
    answer.summary = answer.cause.immediate = "Docker reports a running unhealthy process."
    answer.cause.unknowns = [unknown]
    check_causality(answer, "running_unhealthy")


def test_temporal_database_history_does_not_assert_a_shutdown_cause() -> None:
    answer = _answer("clean_shutdown")
    assert answer.cause
    answer.cause.immediate = "The container exited with code 0 after encountering repeated database errors."
    check_causality(answer, "clean_shutdown")
    for causal in ("because of", "due to"):
        answer.cause.immediate = f"The container exited with code 0 {causal} repeated database errors."
        with pytest.raises(AssertionError):
            check_causality(answer, "clean_shutdown")


def test_whether_fragment_preserves_an_unresolved_shutdown_question() -> None:
    answer = _answer("clean_shutdown")
    assert answer.cause
    answer.summary = answer.cause.immediate = "Docker reports exit 0."
    answer.cause.unknowns = ["Whether the application's shutdown was intentional or triggered by another component."]
    check_causality(answer, "clean_shutdown")


def test_except_kernel_oom_does_not_inherit_negation_of_other_missing_observations() -> None:
    answer = _answer("oom")
    assert answer.cause
    answer.summary = answer.cause.immediate = "Зафиксировано OOM-завершение контейнера."
    answer.cause.unknowns = [
        "Нет метрик и данных \u043e healthcheck, неизвестен другой инициатор завершения, "
        "кроме ядра \u041e\u0421 при OOM."
    ]
    check_causality(answer, "oom")
    answer.summary = "OOM-завершение не подтверждено."
    with pytest.raises(AssertionError):
        check_causality(answer, "oom")


@pytest.mark.parametrize(
    "text",
    ["The container was killed by the OOM killer.", "Контейнер был убит системой управления памятью (OOM Killer)."],
)
def test_oom_killer_names_the_confirmed_event_in_either_language(text: str) -> None:
    answer = _answer("oom")
    assert answer.cause
    answer.summary = answer.cause.immediate = text
    check_causality(answer, "oom")
    unexplained = _answer("unknown_exit")
    unexplained.summary = text
    with pytest.raises(AssertionError):
        check_causality(unexplained, "unknown_exit")
