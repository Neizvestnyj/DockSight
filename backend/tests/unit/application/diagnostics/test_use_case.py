import json
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest

from docksight.adapters.outbound.memory.sessions import MemorySessions
from docksight.application.diagnostics.use_case import Diagnostics
from docksight.application.ports.models import ModelReply, ToolCall
from docksight.application.redaction import Redactor
from docksight.domain.runtime import ContainerSnapshot, StackSummary
from tests.fakes import DiscoveryRuntime, FakeRuntime, ScriptedModel


def proposal(evidence_id: str = "e1") -> str:
    """Build a valid diagnosis proposal linked to collected test evidence."""
    return json.dumps(
        {
            "summary": "Worker exited; inspect its dependency",
            "uncertain": True,
            "evidence_ids": [evidence_id],
            "widgets": [{"widget_type": "container_status", "evidence_ids": [evidence_id], "action": None}],
        }
    )


async def test_observed_namespace_collision_requests_selection_without_calling_the_model() -> None:
    runtime = DiscoveryRuntime()
    model = ScriptedModel([])
    with patch.object(runtime, "stacks", AsyncMock(return_value=(StackSummary("vintoria-infra", "swarm", 1, 0),))):
        events = [
            event
            async for event in Diagnostics(runtime, model, MemorySessions(), Redactor()).stream(
                "alice",
                "local",
                "What happened to vintoria-infra?",
            )
        ]
    assert events[-1]["type"] == "turn.completed"
    selection = next(event["selection"] for event in events if event["type"] == "clarification.required")
    assert {row["kind"] for row in selection["candidates"]} == {"compose", "swarm"}
    assert not any(event["type"] == "answer.ready" for event in events)
    assert not runtime.reads
    assert not model.requests


@pytest.mark.parametrize("query", ["Что не так \u0441 винтория инфра?", "Check the vintoria infrastructure group"])
async def test_agent_selects_an_observed_group_from_noncanonical_spelling(query: str) -> None:
    runtime = DiscoveryRuntime()
    model = ScriptedModel(
        [
            ModelReply("", (ToolCall("group", "inspect_group", {"kind": "compose", "name": "vintoria-infra"}),)),
            ModelReply("Ready"),
            ModelReply(
                json.dumps({"summary": "Two members failed", "uncertain": True, "evidence_ids": ["e1"], "widgets": []})
            ),
        ]
    )
    events = [
        event
        async for event in Diagnostics(runtime, model, MemorySessions(), Redactor()).stream("alice", "local", query)
    ]
    catalog = [message.content for message in model.requests[0][0] if '"available_groups"' in message.content]
    assert len(catalog) == 1
    assert {row["name"] for row in json.loads(catalog[0])["available_groups"]} == {"vintoria-infra", "other-project"}
    assert events[-1]["type"] == "turn.completed"
    answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
    assert answer["group"]["summary"]["name"] == "vintoria-infra"
    assert len(answer["widgets"]) == 4
    assert set(runtime.reads) == {"1" * 64, "2" * 64}


@pytest.mark.parametrize("prose_first", [False, True])
async def test_agent_group_selection_ends_without_finalization_or_later_tool_calls(prose_first: bool) -> None:
    runtime = DiscoveryRuntime()
    candidates = [{"kind": "compose", "name": name} for name in ("vintoria-infra", "other-project")]
    model = ScriptedModel(
        [
            *([ModelReply("Please choose vintoria-infra or other-project")] if prose_first else []),
            ModelReply(
                "",
                (
                    ToolCall("choose", "request_group_selection", {"candidates": candidates}),
                    ToolCall("outside", "get_container_logs", {"container_id": "3" * 64}),
                ),
            ),
        ]
    )
    events = [
        event
        async for event in Diagnostics(runtime, model, MemorySessions(), Redactor()).stream(
            "alice", "local", "Check that infrastructure project"
        )
    ]
    selections = [event for event in events if event["type"] == "clarification.required"]
    assert len(selections) == 1
    assert selections[0]["selection"]["candidates"] == list(reversed(candidates))
    assert events[-1]["type"] == "turn.completed"
    assert not any(event["type"] == "answer.ready" for event in events)
    assert not runtime.reads
    assert len(model.requests) == 1 + int(prose_first)


async def test_diagnosis_uses_real_snapshots_and_never_exposes_write_tools() -> None:
    runtime = FakeRuntime()
    model = ScriptedModel(
        [
            ModelReply("", (ToolCall("c1", "inspect_container", {"container_id": "worker"}),)),
            ModelReply("Ready"),
            ModelReply(proposal()),
        ]
    )
    service = Diagnostics(runtime, model, MemorySessions(), Redactor())
    events = [event async for event in service.stream("alice", "local", "Why did worker exit?")]
    answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
    assert answer["widgets"][0]["snapshot"]["state"] == "exited"
    assert not runtime.mutations
    assert events[-1]["type"] == "turn.completed"


async def test_unknown_evidence_gets_one_repair_attempt() -> None:
    model = ScriptedModel([ModelReply("Ready"), ModelReply(proposal("invented")), ModelReply(proposal("invented"))])
    events = [
        event
        async for event in Diagnostics(FakeRuntime(), model, MemorySessions(), Redactor()).stream(
            "alice", "local", "Inspect"
        )
    ]
    assert len(model.requests) == 3
    assert events[-1]["type"] == "turn.failed"
    assert not any(event["type"] == "answer.ready" for event in events)


def repair_feedback(model: ScriptedModel) -> dict[str, object]:
    """Read structured correction details from the final model request."""
    content = model.requests[-1][0][-1].content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pytest.fail("Repair must explain the validation failure with structured feedback")


async def test_mixed_container_repair_explains_failure_and_valid_evidence_groups() -> None:
    class InventoryRuntime(FakeRuntime):
        """Expose two distinct containers for exact-resource card validation."""

        async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
            """Return a worker and a separate database container."""
            return self.item, replace(self.item, id="b" * 64, name="database")

    invalid = json.loads(proposal())
    invalid["evidence_ids"] = ["e1", "e2"]
    invalid["widgets"][0]["evidence_ids"] = ["e1", "e2"]
    corrected = {
        **invalid,
        "widgets": [
            {"widget_type": "container_status", "evidence_ids": ["e1"]},
            {"widget_type": "container_status", "evidence_ids": ["e2"]},
        ],
    }
    model = ScriptedModel(
        [
            ModelReply("", (ToolCall("c1", "list_containers", {}),)),
            ModelReply("Ready"),
            ModelReply(json.dumps(invalid)),
            ModelReply(json.dumps(corrected)),
        ]
    )
    runtime = InventoryRuntime()
    events = [
        event
        async for event in Diagnostics(runtime, model, MemorySessions(), Redactor()).stream(
            "alice", "local", "Check the worker and database"
        )
    ]
    feedback = repair_feedback(model)
    assert feedback["error"] == {
        "code": "invalid_evidence",
        "message": "Card requires evidence for one exact container",
    }
    assert feedback["evidence_ids"] == ["e1", "e2"]
    assert feedback["container_evidence_groups"] == [["e1"], ["e2"]]
    assert feedback["log_evidence_ids"] == []
    assert feedback["stack_evidence_ids"] == []
    assert feedback["separate_card_examples"] == [
        {"widget_type": "container_status", "evidence_ids": ["e1"]},
        {"widget_type": "container_status", "evidence_ids": ["e2"]},
    ]
    answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
    assert [card["snapshot"]["id"] for card in answer["widgets"]] == ["a" * 64, "b" * 64]
    assert events[-1]["type"] == "turn.completed"
    assert not runtime.mutations


async def test_schema_repair_reports_field_errors_without_model_values() -> None:
    invalid = {
        "summary": "private-model-summary",
        "uncertain": "private-invalid-value",
        "evidence_ids": [],
        "widgets": [],
    }
    corrected = {**invalid, "summary": "Insufficient evidence", "uncertain": True}
    model = ScriptedModel([ModelReply("Ready"), ModelReply(json.dumps(invalid)), ModelReply(json.dumps(corrected))])
    events = [
        event
        async for event in Diagnostics(FakeRuntime(), model, MemorySessions(), Redactor()).stream(
            "alice", "local", "Check"
        )
    ]
    feedback = repair_feedback(model)
    assert feedback["error"] == {
        "code": "invalid_schema",
        "issues": [{"type": "bool_parsing", "loc": ["uncertain"]}],
    }
    assert feedback["evidence_ids"] == []
    assert "private-model-summary" not in json.dumps(feedback)
    assert "private-invalid-value" not in json.dumps(feedback)
    assert events[-1]["type"] == "turn.completed"


async def test_evidence_only_cause_gets_one_repair_before_becoming_a_public_answer() -> None:
    invalid = json.loads(proposal())
    invalid["cause"] = {"immediate": "e1", "evidence_ids": ["e1"]}
    corrected = json.loads(proposal())
    corrected["cause"] = {"immediate": "Worker exited during startup", "evidence_ids": ["e1"]}
    model = ScriptedModel(
        [
            ModelReply("", (ToolCall("inspect", "inspect_container", {"container_id": "worker"}),)),
            ModelReply("Ready"),
            ModelReply(json.dumps(invalid)),
            ModelReply(json.dumps(corrected)),
        ]
    )
    events = [
        event
        async for event in Diagnostics(FakeRuntime(), model, MemorySessions(), Redactor()).stream(
            "alice",
            "local",
            "Inspect worker",
        )
    ]
    answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
    assert len(model.requests) == 4
    assert answer["cause"]["immediate"] == "Worker exited during startup"
    assert events[-1]["type"] == "turn.completed"


async def test_action_schema_repair_supplies_null_constraints_without_echoing_the_rejected_reason() -> None:
    invalid = {
        "summary": "Database connection failed",
        "uncertain": True,
        "evidence_ids": ["e2"],
        "widgets": [
            {
                "widget_type": "log_anomalies",
                "evidence_ids": ["e2"],
                "action": None,
                "action_reason": "private-model-reason",
            }
        ],
    }
    corrected = {**invalid, "widgets": [{"widget_type": "log_anomalies", "evidence_ids": ["e2"]}]}
    model = ScriptedModel(
        [
            ModelReply("", (ToolCall("logs", "get_container_logs", {"container_id": "worker"}),)),
            ModelReply("Ready"),
            ModelReply(json.dumps(invalid)),
            ModelReply(json.dumps(corrected)),
        ]
    )
    events = [
        event
        async for event in Diagnostics(FakeRuntime(), model, MemorySessions(), Redactor()).stream(
            "alice",
            "local",
            "Inspect worker",
        )
    ]
    feedback = repair_feedback(model)
    assert feedback["widget_constraints"] == {
        "non_container_status": {"action": None, "action_reason": None},
        "no_action": {"action_reason": None},
    }
    assert "private-model-reason" not in json.dumps(feedback)
    assert events[-1]["type"] == "turn.completed"


@pytest.mark.parametrize(
    ("nested", "location"),
    [(False, ["<extra_field>"]), (True, ["widgets", 0, "<extra_field>"])],
)
async def test_schema_repair_hides_extra_field_names(nested: bool, location: list[str | int]) -> None:
    invalid = json.loads(proposal())
    target = invalid["widgets"][0] if nested else invalid
    target["private-model-key-secret"] = "private-model-value"
    corrected = '{"summary":"Insufficient evidence","uncertain":true,"evidence_ids":[],"widgets":[]}'
    model = ScriptedModel([ModelReply("Ready"), ModelReply(json.dumps(invalid)), ModelReply(corrected)])
    events = [
        event
        async for event in Diagnostics(FakeRuntime(), model, MemorySessions(), Redactor()).stream(
            "alice", "local", "Inspect"
        )
    ]
    feedback = repair_feedback(model)
    assert feedback["error"] == {
        "code": "invalid_schema",
        "issues": [{"type": "extra_forbidden", "loc": location}],
    }
    assert "private-model-key-secret" not in json.dumps(feedback)
    assert "private-model-value" not in json.dumps(feedback)
    assert events[-1]["type"] == "turn.completed"


@pytest.mark.parametrize(
    ("tool", "arguments", "widget", "groups", "logs", "stacks"),
    [
        ("get_container_logs", {"container_id": "worker"}, "log_anomalies", [["e1", "e2"]], ["e2"], []),
        ("list_stacks", {}, "compose_stack", [], [], ["e1"]),
    ],
)
async def test_repair_preserves_available_log_and_stack_evidence(
    tool: str,
    arguments: dict[str, str],
    widget: str,
    groups: list[list[str]],
    logs: list[str],
    stacks: list[str],
) -> None:
    reference = "e2" if logs else "e1"
    corrected = {
        "summary": "Observed",
        "uncertain": True,
        "evidence_ids": [reference],
        "widgets": [{"widget_type": widget, "evidence_ids": [reference]}],
    }
    model = ScriptedModel(
        [
            ModelReply("", (ToolCall("c1", tool, arguments),)),
            ModelReply("Ready"),
            ModelReply(proposal("invented")),
            ModelReply(json.dumps(corrected)),
        ]
    )
    events = [
        event
        async for event in Diagnostics(FakeRuntime(), model, MemorySessions(), Redactor()).stream(
            "alice", "local", "Inspect"
        )
    ]
    feedback = repair_feedback(model)
    assert feedback["container_evidence_groups"] == groups
    assert feedback["log_evidence_ids"] == logs
    assert feedback["stack_evidence_ids"] == stacks
    answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
    assert answer["widgets"][0]["widget_type"] == widget
    assert answer["widgets"][0]["evidence_ids"] == [reference]
    assert events[-1]["type"] == "turn.completed"


async def test_model_cannot_switch_hosts_through_tool_arguments() -> None:
    model = ScriptedModel(
        [
            ModelReply(
                "",
                (ToolCall("c1", "inspect_container", {"container_id": "worker", "host": "production"}),),
            ),
            ModelReply("Ready"),
            ModelReply('{"summary":"Insufficient evidence","evidence_ids":[],"uncertain":true,"widgets":[]}'),
        ]
    )
    events = [
        event
        async for event in Diagnostics(FakeRuntime(), model, MemorySessions(), Redactor()).stream(
            "alice", "local", "Inspect"
        )
    ]
    tool_result = next(
        message.content for messages, _ in model.requests for message in messages if message.role == "tool"
    )
    assert "invalid_tool_arguments" in tool_result
    assert events[-1]["type"] == "turn.completed"


async def test_exploration_and_repairs_share_the_model_budget() -> None:
    replies = [ModelReply("", (ToolCall(f"c{i}", "list_containers", {}),)) for i in range(4)]
    model = ScriptedModel([*replies, ModelReply("invalid"), ModelReply("invalid")])
    service = Diagnostics(FakeRuntime(), model, MemorySessions(), Redactor(), max_model_calls=6)
    events = [event async for event in service.stream("alice", "local", "Inspect")]
    assert len(model.requests) == 6
    assert events[-1]["type"] == "turn.failed"


async def test_write_tool_injected_by_a_model_is_rejected() -> None:
    runtime = FakeRuntime()
    model = ScriptedModel(
        [
            ModelReply("", (ToolCall("bad", "restart_container", {"container_id": "worker"}),)),
            ModelReply("Ready"),
            ModelReply(
                json.dumps(
                    {
                        "summary": "Unknown cause",
                        "evidence_ids": [],
                        "uncertain": True,
                        "widgets": [],
                    }
                )
            ),
        ]
    )
    events = [
        event
        async for event in Diagnostics(runtime, model, MemorySessions(), Redactor()).stream("alice", "local", "Inspect")
    ]
    assert not runtime.mutations
    assert events[-1]["type"] == "turn.completed"
    assert any(
        "unknown_tool" in message.content for rows, _ in model.requests for message in rows if message.role == "tool"
    )
