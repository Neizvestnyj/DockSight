import pytest
from pydantic import ValidationError

from docksight.application.views.schemas import ActionView, ContainerStatusCard, DiagnosisProposal, WidgetProposal
from tests.fakes import snapshot


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
