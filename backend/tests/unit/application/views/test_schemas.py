import pytest
from pydantic import ValidationError

from docksight.application.views.schemas import (
    ActionView,
    ContainerStatusCard,
    DiagnosisProposal,
    TargetSelection,
    WidgetProposal,
)
from tests.fakes import snapshot


@pytest.mark.parametrize(
    "candidates",
    [
        [{"kind": "container", "id": "a" * 64, "name": "db"}] * 2,
        [{"kind": "compose", "name": "db"}] * 2,
        [{"kind": "container", "id": "a" * 12, "name": "db"}],
        [{"kind": "container", "id": "a" * 64, "name": "db", "host": "other"}],
    ],
)
def test_target_selection_rejects_duplicate_short_or_foreign_container_choices(candidates: list[dict]) -> None:
    with pytest.raises(ValidationError):
        TargetSelection.model_validate({"candidates": candidates})


def test_model_cannot_supply_endpoints_or_runtime_metrics() -> None:
    with pytest.raises(ValidationError):
        DiagnosisProposal.model_validate(
            {
                "summary": "Worker failed",
                "evidence_ids": ["e1"],
                "uncertain": False,
                "widgets": [
                    {
                        "widget_type": "container_status",
                        "evidence_ids": ["e1"],
                        "cpu_percent": 17,
                        "endpoint": "/delete",
                    }
                ],
            }
        )


def test_widget_registry_rejects_unknown_types() -> None:
    with pytest.raises(ValidationError):
        DiagnosisProposal.model_validate(
            {
                "summary": "Check",
                "evidence_ids": [],
                "uncertain": True,
                "widgets": [{"widget_type": "shell", "evidence_ids": []}],
            }
        )


def test_empty_evidence_is_allowed_only_for_uncertain_diagnosis() -> None:
    with pytest.raises(ValidationError):
        DiagnosisProposal.model_validate(
            {
                "summary": "Definitely OOM",
                "evidence_ids": [],
                "uncertain": False,
                "widgets": [],
            }
        )


@pytest.mark.parametrize(
    "payload", [{"action": None, "action_reason": "Restart"}, {"action": "restart", "action_reason": "x" * 241}]
)
def test_action_reason_requires_an_explicit_operation_and_has_a_size_limit(payload: dict) -> None:
    with pytest.raises(ValidationError):
        WidgetProposal(widget_type="container_status", evidence_ids=["e1"], **payload)


@pytest.mark.parametrize(("reference", "host"), [("invented", "local"), ("prepared", "other")])
def test_recommendation_cannot_reference_a_missing_or_foreign_prepared_target(reference: str, host: str) -> None:
    item = snapshot()
    action = ActionView(
        id="prepared",
        host=host,
        container_id=item.id,
        operation="restart",
        expires_at=item.observed_at,
        state="prepared",
        message="Confirm",
    )
    with pytest.raises(ValidationError):
        ContainerStatusCard(
            snapshot=item, evidence_ids=["e1"], actions=[action], recommendation={"action_id": reference}
        )


def test_cause_assessment_requires_evidence_and_keeps_unknowns_separate() -> None:
    proposal = DiagnosisProposal.model_validate(
        {
            "summary": "Startup failed connecting to PostgreSQL",
            "uncertain": True,
            "evidence_ids": ["e1"],
            "widgets": [],
            "cause": {
                "immediate": "Database connection failed during startup",
                "underlying": None,
                "unknowns": ["Why the database connection was refused"],
                "evidence_ids": ["e1"],
            },
        }
    )
    assert proposal.cause is not None
    assert proposal.cause.immediate == "Database connection failed during startup"
    assert proposal.cause.underlying is None


def test_immediate_cause_rejects_a_machine_error_code_as_the_explanation() -> None:
    with pytest.raises(ValidationError, match="human-readable"):
        DiagnosisProposal.model_validate(
            {
                "summary": "Startup failed",
                "uncertain": True,
                "evidence_ids": ["e1"],
                "widgets": [],
                "cause": {
                    "immediate": "database_connection_failure",
                    "underlying": None,
                    "unknowns": [],
                    "evidence_ids": ["e1"],
                },
            }
        )


@pytest.mark.parametrize("field", ["immediate", "underlying", "unknowns"])
@pytest.mark.parametrize("text", ["e3", "e3,e5", '["e1", "e2"]', "[]", "{}", "null", "   "])
def test_cause_text_rejects_evidence_identifiers_and_empty_placeholders(field: str, text: str) -> None:
    cause = {
        "immediate": "Database connection failed during startup",
        "underlying": None,
        "unknowns": [],
        "evidence_ids": ["e1"],
    }
    cause[field] = [text] if field == "unknowns" else text
    with pytest.raises(ValidationError, match="human-readable"):
        DiagnosisProposal.model_validate(
            {
                "summary": "Worker failed during startup",
                "uncertain": True,
                "evidence_ids": ["e1"],
                "widgets": [],
                "cause": cause,
            }
        )


@pytest.mark.parametrize(
    "text", ["OOM killed", "Exit 137 without recorded cause", "Контейнер завершился", "See e1: startup failed"]
)
def test_cause_prose_can_include_technical_terms_codes_and_evidence_citations(text: str) -> None:
    proposal = DiagnosisProposal.model_validate(
        {
            "summary": "Worker failed",
            "uncertain": True,
            "evidence_ids": ["e1"],
            "widgets": [],
            "cause": {"immediate": text, "evidence_ids": ["e1"]},
        }
    )
    assert proposal.cause and proposal.cause.immediate == text
