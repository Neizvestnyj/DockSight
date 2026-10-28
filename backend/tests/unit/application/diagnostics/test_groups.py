import json
from dataclasses import replace

import pytest

from docksight.adapters.outbound.memory.sessions import MemorySessions
from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.diagnostics.tools import DiagnosticTools
from docksight.application.diagnostics.use_case import Diagnostics
from docksight.application.ports.models import ModelReply, ToolCall
from docksight.application.redaction import Redactor
from docksight.application.views.assembler import ViewAssembler
from docksight.application.views.schemas import DiagnosisProposal, GroupTarget
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import ContainerSnapshot, LogBatch, StackMember, StackSummary
from tests.fakes import FakeRuntime, ScriptedModel


class GroupRuntime(FakeRuntime):
    """Expose six failed project members and an unrelated resource."""

    def __init__(self) -> None:
        """Prepare deterministic group membership and record bounded log reads."""
        super().__init__()
        self.rows = tuple(
            replace(self.item, id=str(index) * 64, name=f"worker-{index}", compose_project="infra")
            for index in range(1, 7)
        )
        self.reads: list[str] = []

    async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
        """Include an unrelated container so scope filtering is observable."""
        return (*self.rows, self.item)

    async def inspect(self, host: str, container_id: str) -> ContainerSnapshot:
        """Resolve exact identities, preserving an unrelated resource for rejection tests."""
        return next((row for row in self.rows if row.id == container_id), self.item)

    async def stacks(self, host: str, kind: str) -> tuple[StackSummary, ...]:
        """Return real member summaries rather than model-authored counts."""
        return (
            StackSummary(
                "infra",
                "compose",
                6,
                0,
                tuple(row.id for row in self.rows),
                tuple(StackMember(row.id, row.name, "container", row.state, 1, 0, 1) for row in self.rows),
            ),
        )

    async def logs(self, host: str, container_id: str, lines: int, max_bytes: int) -> LogBatch:
        """Fail one read without hiding other members or retrying it."""
        self.reads.append(container_id)
        if container_id == "2" * 64:
            raise DockSightError("runtime_unavailable", "Docker operation failed", 503)
        return self.log_batch


async def test_group_inspection_keeps_all_member_states_and_reports_failed_and_omitted_logs() -> None:
    runtime = GroupRuntime()
    context = EvidenceContext()
    result = await DiagnosticTools(runtime, context, "local").execute(
        ToolCall("group", "inspect_group", {"kind": "compose", "name": "infra"})
    )
    report = result["group"]
    assert report["summary"]["total"] == 6
    assert len(report["summary"]["members"]) == 6
    assert [row["state"] for row in report["logs"]] == [
        "collected",
        "failed",
        "collected",
        "collected",
        "not_collected",
        "not_collected",
    ]
    assert len(runtime.reads) == 4
    assert report["logs"][1]["code"] == "runtime_unavailable"
    assert any("database unavailable" in json.dumps(row["data"]) for row in result["observations"])
    assert any(row["kind"] == "container" for row in result["observations"])
    assert context.used_bytes <= 65536
    assert not runtime.mutations
    cached = await DiagnosticTools(runtime, context, "local").execute(
        ToolCall("again", "inspect_group", {"kind": "compose", "name": "infra"})
    )
    assert cached == result
    assert len(runtime.reads) == 4


async def test_group_scope_rejects_unrelated_container_reads_and_missing_groups() -> None:
    context = EvidenceContext()
    tools = DiagnosticTools(GroupRuntime(), context, "local")
    await tools.execute(ToolCall("group", "inspect_group", {"kind": "compose", "name": "infra"}))
    with pytest.raises(DockSightError, match="outside the selected group"):
        await tools.execute(ToolCall("outside", "get_container_logs", {"container_id": "worker"}))
    with pytest.raises(DockSightError, match="Group not found"):
        await DiagnosticTools(GroupRuntime(), EvidenceContext(), "local").execute(
            ToolCall("missing", "inspect_group", {"kind": "compose", "name": "missing"})
        )


async def test_server_group_report_survives_a_final_proposal_without_group_widgets() -> None:
    model = ScriptedModel(
        [
            ModelReply("", (ToolCall("group", "inspect_group", {"kind": "compose", "name": "infra"}),)),
            ModelReply("Ready"),
            ModelReply(
                json.dumps({"summary": "Dependency failure", "uncertain": True, "evidence_ids": ["e1"], "widgets": []})
            ),
        ]
    )
    events = [
        event
        async for event in Diagnostics(GroupRuntime(), model, MemorySessions(), Redactor()).stream(
            "alice", "local", "What is wrong with the infra project?"
        )
    ]
    answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
    assert answer["group"]["summary"]["name"] == "infra"
    assert len(answer["group"]["summary"]["members"]) == 6
    assert answer["group"]["evidence_id"] in {row["id"] for row in answer["evidence"]}


async def test_explicit_group_is_collected_before_the_model_and_missing_target_never_falls_back() -> None:
    model = ScriptedModel(
        [
            ModelReply("Ready"),
            ModelReply(
                json.dumps({"summary": "Observed group", "uncertain": True, "evidence_ids": ["e1"], "widgets": []})
            ),
        ]
    )
    service = Diagnostics(GroupRuntime(), model, MemorySessions(), Redactor())
    target = GroupTarget(kind="compose", name="infra")
    events = [event async for event in service.stream("alice", "local", "Check this project", group=target)]
    assert events[-1]["type"] == "turn.completed"
    assert any(message.role == "tool" and '"infra"' in message.content for message in model.requests[0][0])
    missing = GroupTarget(kind="compose", name="missing")
    failed = [event async for event in service.stream("alice", "local", "Check", group=missing)]
    assert failed[-1]["type"] == "turn.failed"
    assert failed[-1]["code"] == "group_not_found"
    assert len(model.requests) == 2


async def test_failed_local_inventory_keeps_the_group_and_reports_missing_log_coverage() -> None:
    class OfflineInventory(GroupRuntime):
        """Fail local discovery after a successful group summary."""

        async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
            """Report a transient local read failure."""
            raise DockSightError("runtime_unavailable", "Docker operation failed", 503)

    context = EvidenceContext()
    result = await DiagnosticTools(OfflineInventory(), context, "local").execute(
        ToolCall("group", "inspect_group", {"kind": "compose", "name": "infra"})
    )
    assert result["group"]["summary"]["total"] == 6
    assert result["group"]["inventory_code"] == "runtime_unavailable"
    assert len(result["group"]["logs"]) == 6
    assert all(row["state"] == "not_collected" for row in result["group"]["logs"])


async def test_oversized_group_summary_is_explicitly_partial_and_leaves_room_for_logs() -> None:
    class LargeGroup(GroupRuntime):
        """Return a wide real-world inventory that exceeds one turn's evidence budget."""

        async def stacks(self, host: str, kind: str) -> tuple[StackSummary, ...]:
            """Keep totals independent of the bounded member preview."""
            members = tuple(
                StackMember(f"{index:064x}", "long-Ж" * 80, "container", "exited", 1, 0, 1) for index in range(200)
            )
            return (StackSummary("infra", "compose", 200, 0, tuple(row.id for row in members), members),)

    context = EvidenceContext()
    result = await DiagnosticTools(LargeGroup(), context, "local").execute(
        ToolCall("group", "inspect_group", {"kind": "compose", "name": "infra"})
    )
    assert result["group"]["summary"]["total"] == 200
    assert result["group"]["summary"]["truncated"] is True
    assert 0 < len(result["group"]["summary"]["members"]) < 200
    assert context.used_bytes < 65536
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= 65536


async def test_group_inventory_cannot_introduce_an_unrelated_card() -> None:
    context = EvidenceContext()
    tools = DiagnosticTools(GroupRuntime(), context, "local")
    await tools.execute(ToolCall("before", "list_containers", {}))
    unrelated = next(ref for ref, row in context.snapshots.items() if row.name == "worker")
    await tools.execute(ToolCall("group", "inspect_group", {"kind": "compose", "name": "infra"}))
    inventory = await tools.execute(ToolCall("after", "list_containers", {}))
    assert all(row["data"]["compose_project"] == "infra" for row in inventory["containers"])
    invalid = DiagnosisProposal.model_validate(
        {
            "summary": "Observed",
            "uncertain": True,
            "evidence_ids": [unrelated],
            "widgets": [{"widget_type": "container_status", "evidence_ids": [unrelated]}],
        }
    )
    with pytest.raises(DockSightError, match="outside the selected group"):
        await ViewAssembler().build(invalid, context, "alice")
