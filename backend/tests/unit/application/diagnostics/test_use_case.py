import json

from docksight.adapters.outbound.memory.sessions import MemorySessions
from docksight.application.diagnostics.use_case import Diagnostics
from docksight.application.ports.models import ModelReply, ToolCall
from docksight.application.redaction import Redactor
from tests.fakes import FakeRuntime, ScriptedModel


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
