from typing import Any, Literal

import pytest

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.views.registry import proposal_schema
from docksight.domain.runtime import LogBatch, StackSummary
from tests.fakes import snapshot


@pytest.mark.parametrize("references", [[], ["e1", "e2"]])
def test_model_schema_limits_every_reference_field_to_current_evidence(references: list[str]) -> None:
    context = EvidenceContext()
    for _ in references:
        context.record("host", "local", {})
    schema: dict[str, Any] = proposal_schema(context)
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
    assert schema["properties"]["widgets"]["type"] == "null"
    assert "enum" not in proposal_schema()["properties"]["evidence_ids"]["items"]


def test_model_schema_does_not_reuse_a_previous_turns_reference_allowlist() -> None:
    previous = EvidenceContext()
    for _ in range(3):
        previous.record("host", "local", {})
    proposal_schema(previous)
    current = EvidenceContext()
    current.record("host", "local", {})
    schema: dict[str, Any] = proposal_schema(current)
    assert schema["properties"]["evidence_ids"]["items"]["enum"] == ["e1"]


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("container", ["container_status", "env_inspector"]),
        ("logs", ["container_status", "log_anomalies", "env_inspector"]),
        ("stack", ["compose_stack"]),
    ],
)
def test_model_schema_only_offers_widget_types_supported_by_typed_evidence(
    kind: Literal["container", "logs", "stack"], expected: list[str]
) -> None:
    context = EvidenceContext()
    context.record(
        kind,
        "local",
        {},
        snapshot=snapshot() if kind != "stack" else None,
        logs=LogBatch(()) if kind == "logs" else None,
        stacks=(StackSummary("demo", "compose", 1, 1),) if kind == "stack" else None,
    )
    schema: dict[str, Any] = proposal_schema(context)
    assert schema["$defs"]["WidgetProposal"]["properties"]["widget_type"]["enum"] == expected
    assert schema["properties"]["widgets"]["maxItems"] == 8


def test_model_schema_does_not_retain_a_previous_turns_widget_restrictions() -> None:
    group = EvidenceContext()
    group.record("stack", "local", {}, stacks=(StackSummary("demo", "compose", 1, 1),))
    proposal_schema(group)
    container = EvidenceContext()
    container.record("container", "local", {}, snapshot=snapshot())
    schema: dict[str, Any] = proposal_schema(container)
    assert schema["$defs"]["WidgetProposal"]["properties"]["widget_type"]["enum"] == [
        "container_status",
        "env_inspector",
    ]
    unrestricted: dict[str, Any] = proposal_schema()
    assert unrestricted["$defs"]["WidgetProposal"]["properties"]["widget_type"]["enum"] == [
        "container_status",
        "log_anomalies",
        "compose_stack",
        "env_inspector",
    ]
