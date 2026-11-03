import json

from docksight.adapters.outbound.memory.sessions import MemorySessions
from docksight.application.diagnostics.use_case import Diagnostics
from docksight.application.ports.models import ModelReply, ToolCall
from docksight.application.redaction import Redactor
from docksight.domain.errors import DockSightError, ErrorKind
from tests.fakes import FakeRuntime, ScriptedModel


def final_proposal(summary: str = "Observed worker exit") -> str:
    """Build a bounded proposal without server-owned runtime or action fields."""
    return json.dumps({"summary": summary, "uncertain": True, "evidence_ids": [], "widgets": []})


async def trace_turn(model: ScriptedModel) -> list[dict]:
    """Run a real diagnostic use case with in-memory ports and a configured secret."""
    service = Diagnostics(FakeRuntime(), model, MemorySessions(), Redactor(("configured-secret",)))
    return [event async for event in service.stream("alice", "local", "Inspect worker")]


async def test_trace_reports_ordered_measured_steps_without_intermediate_text_or_native_replay() -> None:
    model = ScriptedModel(
        [
            ModelReply(
                "<think>private-intermediate-thought</think>Inspect worker",
                (ToolCall("c1", "inspect_container", {"container_id": "worker"}),),
                native=({"reasoning": "private-native-replay"},),
                input_tokens=12,
                output_tokens=0,
            ),
            ModelReply("Ready"),
            ModelReply(final_proposal("password=example configured-secret")),
        ]
    )
    events = await trace_turn(model)
    assert any(event["type"] == "trace.started" for event in events)
    rows = [event["step"] for event in events if event["type"] == "trace.step"]
    finished = [row for row in rows if row["state"] != "running"]
    assert finished[0]["operation"] == "resolve_target"
    finished = finished[1:]
    assert [row["kind"] for row in finished] == ["model", "tool", "model", "model", "validation"]
    assert finished[0]["input_tokens"] == 12
    assert finished[0]["output_tokens"] == 0
    assert finished[2]["input_tokens"] is None
    assert all(row["duration_ms"] >= 0 and row["finished_at"] for row in finished)
    assert rows[0]["state"] == "running"
    assert finished[3]["response"] and "[REDACTED]" in finished[3]["response"]
    serialized = json.dumps(events)
    assert "private-intermediate-thought" not in serialized
    assert "private-native-replay" not in serialized
    assert "configured-secret" not in serialized
    assert events[-1]["type"] == "turn.completed"


async def test_exploration_preview_shows_normalized_text_and_calls_with_sensitive_values_removed() -> None:
    model = ScriptedModel(
        [
            ModelReply(
                "<think>hidden analysis</think>Inspect configured-secret",
                (
                    ToolCall(
                        "c1",
                        "inspect_container",
                        {
                            "container_id": "worker",
                            "password": "opaque-value",
                            "reasoning": "hidden argument",
                            "headers": {
                                "Authorization": "Bearer opaque-bearer",
                                "Proxy-Authorization": "Basic opaque-proxy",
                                "Cookie": "session=opaque-cookie",
                                "Set-Cookie": "session=opaque-set-cookie",
                            },
                        },
                    ),
                ),
                native=({"encrypted_content": "private replay"},),
            ),
            ModelReply("Ready"),
            ModelReply(final_proposal()),
        ]
    )
    events = await trace_turn(model)
    step = next(
        event["step"]
        for event in events
        if event["type"] == "trace.step"
        and event["step"]["operation"] == "collect_evidence"
        and event["step"]["state"] == "succeeded"
    )
    assert step["response"] is not None
    response = json.loads(step["response"])
    assert response == {
        "content": "Inspect [REDACTED]",
        "tool_calls": [
            {
                "id": "c1",
                "name": "inspect_container",
                "arguments": {
                    "container_id": "worker",
                    "password": "[REDACTED]",
                    "reasoning": "[OMITTED]",
                    "headers": {
                        "Authorization": "[REDACTED]",
                        "Proxy-Authorization": "[REDACTED]",
                        "Cookie": "[REDACTED]",
                        "Set-Cookie": "[REDACTED]",
                    },
                },
            }
        ],
    }
    assert "private replay" not in json.dumps(events)
    assert "hidden analysis" not in json.dumps(events)
    assert "opaque-value" not in json.dumps(events)


async def test_schema_failure_retains_repair_trace_but_withholds_unrecognized_model_fields() -> None:
    invalid = json.loads(final_proposal())
    invalid["private-reasoning-field"] = "private-reasoning-value"
    events = await trace_turn(
        ScriptedModel([ModelReply("Ready"), ModelReply(json.dumps(invalid)), ModelReply("not JSON")])
    )
    rows = [event["step"] for event in events if event["type"] == "trace.step" and event["step"]["state"] != "running"]
    failures = [row for row in rows if row["kind"] == "validation"]
    assert [row["code"] for row in failures] == ["invalid_schema", "invalid_schema"]
    assert failures[0]["issues"] == [{"type": "extra_forbidden", "loc": ["<extra_field>"]}]
    assert any(row["operation"] == "repair_response" for row in rows)
    assert all(row["response"] is None for row in rows if row["operation"] in {"final_response", "repair_response"})
    assert "private-reasoning" not in json.dumps(events)
    assert events[-1]["type"] == "turn.failed"


async def test_provider_failure_completes_the_running_trace_step_before_terminal_failure() -> None:
    class UnavailableModel(ScriptedModel):
        """Fail the model boundary without making a provider request."""

        async def complete(self, messages, tools=(), schema=None):
            """Report an expected provider failure without a raw upstream response."""
            raise DockSightError("provider_unavailable", "Model provider is unavailable", ErrorKind.UNAVAILABLE)

    events = await trace_turn(UnavailableModel([]))
    finished = [
        event["step"] for event in events if event["type"] == "trace.step" and event["step"]["state"] == "failed"
    ]
    assert len(finished) == 1
    assert finished[0]["code"] == "provider_unavailable"
    assert finished[0]["duration_ms"] >= 0
    assert events[-2]["type"] == "trace.step"
    assert events[-1]["type"] == "turn.failed"


async def test_trace_redacts_secret_values_before_json_escaping() -> None:
    secret = 'quoted"credential\nvalue'
    model = ScriptedModel([ModelReply("Ready"), ModelReply(final_proposal(f"Observed {secret}"))])
    service = Diagnostics(FakeRuntime(), model, MemorySessions(), Redactor((secret,)))
    events = [event async for event in service.stream("alice", "local", "Inspect")]
    step = next(
        event["step"]
        for event in events
        if event["type"] == "trace.step"
        and event["step"]["operation"] == "final_response"
        and event["step"]["response"] is not None
    )
    assert json.loads(step["response"])["summary"] == "Observed [REDACTED]"


async def test_trace_clips_multibyte_proposals_without_replacing_a_partial_character() -> None:
    proposal = json.loads(final_proposal())
    proposal["evidence_ids"] = ["ж" * 500] * 20
    events = await trace_turn(
        ScriptedModel(
            [ModelReply("Ready"), ModelReply(json.dumps(proposal, ensure_ascii=False)), ModelReply(final_proposal())]
        )
    )
    clipped = next(
        event["step"] for event in events if event["type"] == "trace.step" and event["step"]["response_truncated"]
    )
    assert len(clipped["response"].encode("utf-8")) <= 16384
    assert "\ufffd" not in clipped["response"]
    assert events[-1]["type"] == "turn.completed"


async def test_excess_tool_calls_keep_paired_budget_errors_without_executing_or_tracing_them() -> None:
    model = ScriptedModel(
        [
            ModelReply(
                "", tuple(ToolCall(f"c{index}", "inspect_container", {"container_id": "worker"}) for index in range(3))
            ),
            ModelReply(final_proposal()),
        ]
    )
    service = Diagnostics(FakeRuntime(), model, MemorySessions(), Redactor(), max_tool_calls=1)
    events = [event async for event in service.stream("alice", "local", "Inspect")]
    results = [message for message in model.requests[-1][0] if message.role == "tool"]
    assert [message.tool_call_id for message in results] == ["c0", "c1", "c2"]
    assert [json.loads(message.content)["error"] for message in results[1:]] == ["tool_limit", "tool_limit"]
    actual = [
        event for event in events if event["type"] == "trace.step" and event["step"]["operation"] == "inspect_container"
    ]
    assert len(actual) == 2
    assert events[-1]["type"] == "turn.completed"
