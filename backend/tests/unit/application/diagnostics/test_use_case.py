import json
from collections.abc import Sequence
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest

from docksight.adapters.outbound.memory.sessions import MemorySessions
from docksight.application.diagnostics.use_case import Diagnostics
from docksight.application.ports.models import ModelMessage, ModelReply, ToolCall
from docksight.application.redaction import Redactor
from docksight.application.views.schemas import GroupTarget
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import ContainerSnapshot, LogBatch, StackSummary
from tests.fakes import DiscoveryRuntime, FakeRuntime, ScriptedModel


async def test_selected_diagnoses_share_global_capacity_and_preserve_turn_identity() -> None:
    """Two provider selections cannot bypass the original shared concurrency budget."""
    default = ScriptedModel([])
    first_model, second_model = ScriptedModel([]), ScriptedModel([])
    diagnostics = Diagnostics(FakeRuntime(), default, MemorySessions(), Redactor(), concurrency=1)
    first = diagnostics.with_model(first_model, ("openai", "first"))
    second = diagnostics.with_model(second_model, ("anthropic", "second"))
    stream = first.stream("alice", "local", "Inspect")
    try:
        assert (await anext(stream))["type"] == "turn.started"
        trace = await anext(stream)
        assert trace["type"] == "trace.started"
        assert trace["provider"] == "openai" and trace["model"] == "first"
        rejected = [event async for event in second.stream("alice", "local", "Inspect")]
        assert rejected[-1]["type"] == "turn.failed" and rejected[-1]["code"] == "turn_capacity"
        assert diagnostics.model is default
        assert second_model.requests == []
        assert first.sessions is second.sessions is diagnostics.sessions
        assert first.assembler is second.assembler is diagnostics.assembler
        assert first.redactor is second.redactor is diagnostics.redactor
    finally:
        await stream.aclose()


async def test_switching_model_preserves_session_history_and_trace() -> None:
    """A later selection uses the existing session while earlier events retain their original model identity."""
    answer = '{"summary":"Insufficient evidence","uncertain":true,"evidence_ids":[],"widgets":[]}'
    first_model = ScriptedModel([ModelReply("Ready"), ModelReply(answer)])
    second_model = ScriptedModel([ModelReply("Ready"), ModelReply(answer)])
    diagnostics = Diagnostics(
        FakeRuntime(), first_model, MemorySessions(), Redactor(), model_identity=("ollama", "one")
    )
    first = [event async for event in diagnostics.stream("alice", "local", "Inspect")]
    session_id = next(event["session_id"] for event in first if event["type"] == "turn.started")
    second = diagnostics.with_model(second_model, ("openai", "two"))
    events = [event async for event in second.stream("alice", "local", "What next?", session_id)]
    assert events[-1]["type"] == "turn.completed"
    history = second_model.requests[0][0]
    context = next(message for message in history if "previous_turns" in message.content)
    assert context.role == "user"
    assert json.loads(context.content.split("\n", 1)[1]) == {
        "previous_turns": [
            {"role": "user", "content": "Inspect"},
            {"role": "assistant", "content": "Insufficient evidence"},
        ]
    }
    assert not any(message.role == "assistant" and message.content == "Insufficient evidence" for message in history)
    assert next(event for event in first if event["type"] == "trace.started")["model"] == "one"
    assert next(event for event in events if event["type"] == "trace.started")["model"] == "two"


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


@pytest.mark.parametrize("scope", ["container", "group"])
async def test_final_generation_uses_tool_observations_without_replaying_a_prose_only_draft(scope: str) -> None:
    model = ScriptedModel(
        [
            ModelReply("The process crashed because of historical SQL errors."),
            ModelReply('{"summary":"The cause is unknown","uncertain":true,"evidence_ids":["e1"],"widgets":[]}'),
        ]
    )
    diagnostics = Diagnostics(DiscoveryRuntime(), model, MemorySessions(), Redactor())
    events = [
        event
        async for event in diagnostics.stream(
            "alice",
            "local",
            "Check the target",
            group=GroupTarget(kind="compose", name="vintoria-infra") if scope == "group" else None,
            container_id="1" * 64 if scope == "container" else None,
        )
    ]
    assert events[-1]["type"] == "turn.completed"
    messages, schema = model.requests[-1]
    assert schema is not None
    assert any(message.role == "tool" for message in messages)
    assert any(message.role == "assistant" and message.tool_calls for message in messages)
    assert not any("historical SQL errors" in message.content for message in messages)


async def test_final_generation_repeats_the_current_question_without_its_credential() -> None:
    query = "Check container worker; token=fixture-credential"
    model = ScriptedModel([ModelReply("Ready"), ModelReply(proposal())])
    events = [
        event
        async for event in Diagnostics(FakeRuntime(), model, MemorySessions(), Redactor()).stream(
            "alice", "local", query, container_id="a" * 64
        )
    ]
    assert events[-1]["type"] == "turn.completed"
    assert "Check container worker; token=[REDACTED]" in model.requests[-1][0][-1].content
    assert all("fixture-credential" not in message.content for messages, _ in model.requests for message in messages)


@pytest.mark.parametrize("additional_read", [False, True])
async def test_repeated_successful_batch_finalizes_but_a_new_read_continues_exploration(additional_read: bool) -> None:
    target = GroupTarget(kind="compose", name="vintoria-infra")
    calls = [ToolCall("repeat", "inspect_group", target.model_dump())]
    if additional_read:
        calls.append(ToolCall("new", "get_container_stats", {"container_id": "1" * 64}))
    native = ({"type": "provider-replay", "id": "retained"},)
    replies = [ModelReply("", tuple(calls), native=native)]
    if additional_read:
        replies.append(ModelReply("Ready"))
    answer = '{"summary":"Unknown cause","uncertain":true,"evidence_ids":["e1"],"widgets":[]}'
    model = ScriptedModel([*replies, ModelReply(answer)])
    events = [
        event
        async for event in Diagnostics(DiscoveryRuntime(), model, MemorySessions(), Redactor()).stream(
            "alice", "local", "Check the project", group=target
        )
    ]
    assert events[-1]["type"] == "turn.completed"
    assert len(model.requests) == (3 if additional_read else 2)
    messages, final = model.requests[-1]
    assert final
    assert next(row for row in messages if row.native).native == native
    results = {row.tool_call_id: json.loads(row.content) for row in messages if row.role == "tool"}
    assert results["repeat"]["already_collected"] is True
    assert "group" in results["selected-group"]
    assert {call.id for row in messages for call in row.tool_calls} == set(results)
    if additional_read:
        assert "data" in results["new"]


async def test_follow_up_keeps_prior_explanation_as_context_and_collects_the_new_target() -> None:
    answer = '{"summary":"Earlier backend failure","uncertain":true,"evidence_ids":["e1"],"widgets":[]}'
    model = ScriptedModel([ModelReply("Ready"), ModelReply(answer), ModelReply("Ready"), ModelReply(proposal())])
    sessions = MemorySessions()
    runtime = DiscoveryRuntime()
    service = Diagnostics(runtime, model, sessions, Redactor())
    first_query = "Inspect backend-1 token=fixture-secret"
    first = [event async for event in service.stream("alice", "local", first_query, container_id="1" * 64)]
    session_id = next(event["session_id"] for event in first if event["type"] == "turn.started")
    query = "Is this related to the previous failure?"
    second = [event async for event in service.stream("alice", "local", query, session_id, container_id="3" * 64)]
    assert second[-1]["type"] == "turn.completed"
    for messages, _ in model.requests[2:]:
        _assert_follow_up_context(messages, query)
        scope = next(json.loads(row.content) for row in messages if '"selected_container_id"' in row.content)
        assert scope["selected_container_id"] == "3" * 64
    assert runtime.reads == ["1" * 64, "3" * 64]
    async with sessions.lease(session_id, "alice", "local") as session:
        assert [row.content for row in session.history[:2]] == [
            "Inspect backend-1 token=[REDACTED]",
            "Earlier backend failure",
        ]


def _assert_follow_up_context(messages: Sequence[ModelMessage], query: str) -> None:
    """Check that relative follow-ups retain redacted context without promoting earlier conclusions."""
    context = next(message for message in messages if "previous_turns" in message.content)
    assert context.role == "user"
    previous = json.loads(context.content.split("\n", 1)[1])["previous_turns"]
    assert previous == [
        {"role": "user", "content": "Inspect backend-1 token=[REDACTED]"},
        {"role": "assistant", "content": "Earlier backend failure"},
    ]
    assert any(row.role == "user" and row.content == query for row in messages)
    assert all("fixture-secret" not in row.content for row in messages)
    assert not any(row.role == "assistant" and row.content == "Earlier backend failure" for row in messages)


async def test_selected_container_retains_its_status_when_prefetched_logs_are_unavailable() -> None:
    class MissingLogs(FakeRuntime):
        """Expose an inspectable container whose log driver cannot return a batch."""

        async def logs(self, host: str, container_id: str, lines: int, max_bytes: int) -> LogBatch:
            """Fail only the log read after the runtime snapshot has been recorded."""
            raise DockSightError("logs_unavailable", "Container logs are unavailable", 502)

    model = ScriptedModel([ModelReply("Ready"), ModelReply(proposal())])
    events = [
        event
        async for event in Diagnostics(MissingLogs(), model, MemorySessions(), Redactor()).stream(
            "alice",
            "local",
            "Check container worker",
        )
    ]
    assert events[-1]["type"] == "turn.completed"
    answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
    assert answer["widgets"][0]["snapshot"]["id"] == "a" * 64
    assert any(
        event["type"] == "tool.completed" and event["tool"] == "get_container_logs" and not event["ok"]
        for event in events
    )


async def test_conflicting_explicit_targets_fail_before_model_or_tool_execution() -> None:
    model = ScriptedModel([])
    events = [
        event
        async for event in Diagnostics(FakeRuntime(), model, MemorySessions(), Redactor()).stream(
            "alice", "local", "Inspect", group=GroupTarget(kind="compose", name="infra"), container_id="a" * 64
        )
    ]
    assert len(events) == 1
    assert events[0]["type"] == "turn.failed" and events[0]["code"] == "invalid_target"
    assert not model.requests


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


async def test_final_and_repair_schemas_restrict_log_quotations_to_fresh_evidence_ids() -> None:
    quoted = 'invalid input value for enum login_provider: "unknown"'
    model = ScriptedModel([ModelReply("Ready"), ModelReply(proposal(quoted)), ModelReply(proposal())])
    runtime = FakeRuntime()
    service = Diagnostics(runtime, model, MemorySessions(), Redactor())
    with patch.object(model, "complete", wraps=model.complete) as complete:
        events = [
            event
            async for event in service.stream(
                "alice", "local", "Could the database be stopped?", container_id=runtime.item.id
            )
        ]
    assert events[-1]["type"] == "turn.completed"
    assert any(event["type"] == "trace.step" and event["step"]["code"] == "invalid_evidence" for event in events)
    for call in complete.call_args_list[1:]:
        schema = call.kwargs["schema"]
        assert schema["properties"]["evidence_ids"]["items"]["enum"] == ["e1", "e2"]
        assert schema["$defs"]["WidgetProposal"]["properties"]["evidence_ids"]["items"]["enum"] == ["e1", "e2"]
        assert schema["$defs"]["CauseAssessment"]["properties"]["evidence_ids"]["items"]["enum"] == ["e1", "e2"]
    answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
    assert {row["id"] for row in answer["evidence"]} == {"e1", "e2"}
    assert not runtime.mutations


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
    calls = [
        ToolCall("inventory", "list_containers", {}),
        ToolCall("inspect", "inspect_container", {"container_id": "worker"}),
        ToolCall("logs", "get_container_logs", {"container_id": "worker"}),
        ToolCall("stats", "get_container_stats", {"container_id": "worker"}),
    ]
    replies = [ModelReply("", (call,)) for call in calls]
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
