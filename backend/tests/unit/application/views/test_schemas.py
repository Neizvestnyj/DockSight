import pytest
from pydantic import ValidationError

from docksight.application.views.schemas import DiagnosisProposal


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
