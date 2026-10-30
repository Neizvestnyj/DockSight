from typing import Any

import pytest

from docksight.application.views.registry import proposal_schema


@pytest.mark.parametrize("references", [[], ["e1", "e2"]])
def test_model_schema_limits_every_reference_field_to_current_evidence(references: list[str]) -> None:
    schema: dict[str, Any] = proposal_schema(references)
    fields = [
        schema["properties"]["evidence_ids"],
        schema["$defs"]["CauseAssessment"]["properties"]["evidence_ids"],
        schema["$defs"]["WidgetProposal"]["properties"]["evidence_ids"],
    ]
    for field in fields:
        if references:
            assert field["items"]["enum"] == references
        else:
            assert field["maxItems"] == 0
            assert "enum" not in field["items"]
    assert "enum" not in proposal_schema()["properties"]["evidence_ids"]["items"]


def test_model_schema_does_not_reuse_a_previous_turns_reference_allowlist() -> None:
    proposal_schema(["e1", "e2", "e3"])
    schema: dict[str, Any] = proposal_schema(["e1"])
    assert schema["properties"]["evidence_ids"]["items"]["enum"] == ["e1"]
