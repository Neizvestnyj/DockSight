import json
from dataclasses import replace

import pytest

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.diagnostics.tools import DiagnosticTools
from docksight.application.diagnostics.use_case import Diagnostics
from docksight.application.ports.models import ModelReply, ToolCall
from docksight.application.redaction import Redactor
from docksight.application.views.assembler import ViewAssembler
from docksight.application.views.schemas import DiagnosisProposal, HostInspection, WidgetProposal
from docksight.domain.errors import DockSightError, ErrorKind
from docksight.domain.runtime import ContainerSnapshot, LogBatch, LogEntry, StackSummary
from tests.diagnostics import diagnostic_stream
from tests.fakes import FakeRuntime, ScriptedModel


class HostRuntime(FakeRuntime):
    """Expose failures in two projects and an ungrouped container without changing Docker."""

    def __init__(self) -> None:
        """Mix process failures, unhealthy state, a normal exit, and an otherwise healthy process."""
        super().__init__()
        self.rows = tuple(
            replace(self.item, id=f"{index:064x}", name=f"service-{index}", compose_project=f"project-{index % 2}")
            for index in range(1, 7)
        )
        self.rows = (
            self.rows[0],
            replace(self.rows[1], state="running", exit_code=0, health="unhealthy"),
            replace(self.rows[2], compose_project=None, oom_killed=True, exit_code=137),
            replace(self.rows[3], state="running", exit_code=0, health="healthy"),
            replace(self.rows[4], exit_code=0),
            replace(self.rows[5], state="restarting"),
        )
        self.reads: list[str] = []
        self.failures: set[str] = set()
        self.swarm_error = False

    async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
        """Return this selected engine's inventory in an order that is not a severity ranking."""
        return self.rows

    async def inspect(self, host: str, container_id: str) -> ContainerSnapshot:
        """Resolve only exact observed identities."""
        return next(row for row in self.rows if row.id == container_id)

    async def stacks(self, host: str, kind: str) -> tuple[StackSummary, ...]:
        """Allow optional manager metadata failure without losing local container observations."""
        if self.swarm_error:
            raise DockSightError("runtime_unavailable", "Swarm discovery failed", ErrorKind.UNAVAILABLE)
        return ()

    async def logs(self, host: str, container_id: str, lines: int, max_bytes: int) -> LogBatch:
        """Record finite reads and preserve failures as failures rather than empty successful logs."""
        self.reads.append(container_id)
        if container_id in self.failures:
            raise DockSightError("runtime_unavailable", "Docker log read failed", ErrorKind.UNAVAILABLE)
        return self.log_batch


def _model(*replies: ModelReply) -> ScriptedModel:
    """Omit model widgets so the server's factual overview and detail-card policy are exercised."""
    return ScriptedModel(
        [
            *replies,
            ModelReply("Ready"),
            ModelReply(
                json.dumps(
                    {
                        "summary": "Several containers need inspection",
                        "uncertain": True,
                        "evidence_ids": ["e1"],
                        "widgets": [],
                    }
                )
            ),
        ]
    )


def _assert_host_members(report: HostInspection) -> None:
    """Compare the overview with literal fixture facts, including the ungrouped failure and omitted logs."""
    assert (report.total, report.running, report.attention) == (6, 2, 5)
    assert {row.group.name for row in report.members if row.group} == {"project-0", "project-1"}
    assert any(row.container_id == f"{3:064x}" and row.group is None for row in report.members)
    assert [row.state for row in report.logs].count("not_collected") == 1


@pytest.mark.parametrize("query", ["What happened?", "Что случилось?"])
async def test_bare_question_collects_a_host_overview_before_model_explanations(query: str) -> None:
    runtime, model = HostRuntime(), _model()
    events = [event async for event in diagnostic_stream(Diagnostics(runtime, model, Redactor()), "a", "local", query)]
    assert events[-1]["type"] == "turn.completed", events[-1]
    assert not any(event["type"] == "clarification.required" for event in events)
    answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
    report = HostInspection.model_validate(answer["host_overview"])
    assert answer["group"] is None
    _assert_host_members(report)
    assert set(runtime.reads) == {f"{index:064x}" for index in (1, 2, 3, 6)}
    assert len(answer["widgets"]) == 8
    assert any(row["kind"] == "host" and row["id"] == report.evidence_id for row in answer["evidence"])
    assert any(message.role == "tool" and "service-3" in message.content for message in model.requests[0][0])
    assert not runtime.mutations


async def test_model_cannot_replace_host_overview_with_a_group_choice() -> None:
    runtime = HostRuntime()
    model = _model(
        ModelReply(
            "",
            (
                ToolCall(
                    "choose",
                    "request_group_selection",
                    {
                        "candidates": [
                            {"kind": "compose", "name": "project-0"},
                            {"kind": "compose", "name": "project-1"},
                        ]
                    },
                ),
            ),
        )
    )
    events = [
        event
        async for event in diagnostic_stream(Diagnostics(runtime, model, Redactor()), "a", "local", "What failed?")
    ]
    assert events[-1]["type"] == "turn.completed", events[-1]
    assert not any(event["type"] == "clarification.required" for event in events)
    assert any(event["type"] == "answer.ready" and event["answer"]["host_overview"] for event in events)
    assert len(runtime.reads) == 4


async def test_failed_logs_keep_observed_status_and_swarm_failure_stays_explicit() -> None:
    runtime = HostRuntime()
    runtime.failures.add(f"{2:064x}")
    runtime.swarm_error = True
    model = _model()
    events = [
        event
        async for event in diagnostic_stream(Diagnostics(runtime, model, Redactor()), "a", "local", "What happened?")
    ]
    answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
    report = answer["host_overview"]
    assert report["discovery_code"] == "runtime_unavailable"
    failure = next(row for row in report["logs"] if row["container_id"] == f"{2:064x}")
    assert failure["state"] == "failed" and failure["code"] == "runtime_unavailable"
    assert any(
        widget["widget_type"] == "container_status" and widget["snapshot"]["health"] == "unhealthy"
        for widget in answer["widgets"]
    )
    assert len(answer["widgets"]) == 7


async def test_host_tool_caps_inventory_preview_targets_and_log_reads() -> None:
    runtime, context = HostRuntime(), EvidenceContext()
    runtime.rows = tuple(
        replace(runtime.item, id=f"{index:064x}", name="容" * 256 + str(index), compose_project=f"project-{index}")
        for index in range(250)
    )
    tools = DiagnosticTools(runtime, context, "local", inventory=runtime.rows)
    result = await tools.execute(ToolCall("host", "inspect_host", {}))
    report = result["overview"]
    assert report["total"] == report["attention"] == 200
    assert report["truncated"]
    assert 0 < len(report["members"]) <= 32
    assert len(report["targets"]) <= 32
    assert len(runtime.reads) <= 4
    assert context.used_bytes <= 65536
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= 65536
    assert await tools.execute(ToolCall("again", "inspect_host", {})) == {
        "already_collected": True,
        "evidence_ids": list(context.evidence),
    }
    assert len(runtime.reads) <= 4


async def test_empty_host_has_no_invented_problem_or_log_reads() -> None:
    runtime = HostRuntime()
    runtime.rows = ()
    result = await DiagnosticTools(runtime, EvidenceContext(), "local").execute(ToolCall("host", "inspect_host", {}))
    assert result["overview"]["total"] == result["overview"]["attention"] == 0
    assert result["overview"]["members"] == result["overview"]["logs"] == []
    assert not result["overview"]["truncated"]
    assert not runtime.reads


@pytest.mark.parametrize("recovered", [False, True])
async def test_later_log_reads_update_host_coverage_and_survive_omitted_widgets(recovered: bool) -> None:
    runtime, context = HostRuntime(), EvidenceContext()
    container_id = f"{2 if recovered else 5:064x}"
    if recovered:
        runtime.failures.add(container_id)
    tools = DiagnosticTools(runtime, context, "local", inventory=runtime.rows)
    await tools.execute(ToolCall("host", "inspect_host", {}))
    runtime.failures.clear()
    result = await tools.execute(ToolCall("more", "get_container_logs", {"container_id": container_id}))
    answer = await ViewAssembler().build(
        DiagnosisProposal(summary="Review collected observations", uncertain=True, evidence_ids=[], widgets=[]),
        context,
        "actor",
    )
    assert answer.host_overview is not None
    coverage = next(row for row in answer.host_overview.logs if row.container_id == container_id)
    assert (coverage.state, coverage.code, coverage.evidence_id) == ("collected", None, result["evidence_id"])
    assert result["evidence_id"] in {row.id for row in answer.evidence}
    assert any(card.widget_type == "log_anomalies" and card.container_id == container_id for card in answer.widgets)
    assert len(runtime.reads) == 5


@pytest.mark.parametrize("full_proposal", [False, True])
async def test_reads_outside_host_preview_keep_evidence_within_card_capacity(full_proposal: bool) -> None:
    runtime, context = HostRuntime(), EvidenceContext()
    runtime.rows = tuple(replace(runtime.item, id=f"{i:064x}", name=f"service-{i:02}") for i in range(40))
    tools = DiagnosticTools(runtime, context, "local", inventory=runtime.rows)
    await tools.execute(ToolCall("host", "inspect_host", {}))
    assert context.host_overview is not None
    outside = runtime.rows[-1].id
    assert outside not in {row.container_id for row in context.host_overview.members}
    proposed = [WidgetProposal(widget_type="env_inspector", evidence_ids=[ref]) for ref in context.snapshots][:8]
    result = await tools.execute(ToolCall("more", "get_container_logs", {"container_id": outside}))
    answer = await ViewAssembler().build(
        DiagnosisProposal(
            summary="Review collected observations",
            uncertain=True,
            evidence_ids=[],
            widgets=proposed if full_proposal else [],
        ),
        context,
        "actor",
    )
    assert result["evidence_id"] in {row.id for row in answer.evidence}
    assert len(answer.widgets) <= 16
    assert all(row.container_id != outside for row in context.host_overview.logs)
    if not full_proposal:
        assert any(card.widget_type == "log_anomalies" and card.container_id == outside for card in answer.widgets)


async def test_host_projection_bounds_the_actual_unicode_tool_message() -> None:
    runtime, model = HostRuntime(), _model()
    runtime.rows = tuple(
        replace(runtime.item, id=f"{i:064x}", name="a" * 256 + str(i), compose_project=f"project-{i}")
        for i in range(40)
    )
    runtime.log_batch = LogBatch((LogEntry("Ошибка" * 300),))
    events = [
        event
        async for event in diagnostic_stream(Diagnostics(runtime, model, Redactor()), "a", "local", "What happened?")
    ]
    assert events[-1]["type"] == "turn.completed", events[-1]
    projections = [message.content for message in model.requests[0][0] if message.tool_name == "inspect_host"]
    assert projections
    assert all(len(content.encode()) <= 65536 for content in projections)


async def test_model_host_projection_limits_member_detail_without_clipping_the_public_overview() -> None:
    runtime, context = HostRuntime(), EvidenceContext()
    runtime.rows = tuple(
        replace(runtime.item, id=f"{i:064x}", name=f"worker-{i}", state="exited" if i < 5 else "running")
        for i in range(21)
    )
    result = await DiagnosticTools(runtime, context, "local", inventory=runtime.rows).execute(
        ToolCall("host", "inspect_host", {})
    )
    assert context.host_overview is not None
    assert len(context.host_overview.members) == 21 and not context.host_overview.truncated
    assert len(result["overview"]["members"]) <= 8
    assert result["projection_truncated"] is True
    assert result["overview"]["total"] == 21
    assert {row["container_id"] for row in result["overview"]["members"]} >= {f"{i:064x}" for i in range(5)}


async def test_host_finalization_keeps_evidence_without_replaying_the_unvalidated_draft() -> None:
    runtime, model = HostRuntime(), _model()
    events = [
        event
        async for event in diagnostic_stream(Diagnostics(runtime, model, Redactor()), "a", "local", "What happened?")
    ]
    assert events[-1]["type"] == "turn.completed"
    messages, schema = model.requests[1]
    assert schema is not None
    assert any(message.tool_name == "inspect_host" for message in messages)
    assert not any(message.role == "assistant" and message.content == "Ready" for message in messages)


@pytest.mark.parametrize("scope", ["group", "container"])
async def test_host_tool_cannot_expand_an_explicit_target(scope: str) -> None:
    from docksight.application.views.schemas import GroupTarget

    runtime = HostRuntime()
    tools = DiagnosticTools(
        runtime,
        EvidenceContext(),
        "local",
        group=GroupTarget(kind="compose", name="project-0") if scope == "group" else None,
        container_id=runtime.rows[0].id if scope == "container" else None,
    )
    with pytest.raises(DockSightError) as caught:
        await tools.execute(ToolCall("host", "inspect_host", {}))
    assert caught.value.code in {"resource_outside_group", "resource_outside_container"}
    assert not runtime.reads
