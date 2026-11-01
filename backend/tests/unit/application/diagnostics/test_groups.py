import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from docksight.adapters.outbound.memory.sessions import MemorySessions
from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.diagnostics.scope import resolve_target
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
                len(self.rows),
                sum(row.state == "running" for row in self.rows),
                tuple(row.id for row in self.rows),
                tuple(
                    StackMember(
                        row.id,
                        row.name,
                        "container",
                        row.state,
                        1,
                        int(row.state == "running"),
                        row.exit_code,
                        health=row.health,
                    )
                    for row in self.rows
                ),
            ),
        )

    async def logs(self, host: str, container_id: str, lines: int, max_bytes: int) -> LogBatch:
        """Fail one read without hiding other members or retrying it."""
        self.reads.append(container_id)
        if container_id == "2" * 64:
            raise DockSightError("runtime_unavailable", "Docker operation failed", 503)
        return self.log_batch


async def test_running_unhealthy_member_is_collected_without_restarts_or_oom() -> None:
    runtime = GroupRuntime()
    runtime.rows = tuple(
        replace(row, state="running", exit_code=0, restart_count=0, health="unhealthy" if index == 0 else "starting")
        for index, row in enumerate(runtime.rows)
    )
    context = EvidenceContext()
    result = await DiagnosticTools(runtime, context, "local").execute(
        ToolCall("group", "inspect_group", {"kind": "compose", "name": "infra"})
    )
    assert runtime.reads == ["1" * 64]
    assert result["group"]["summary"]["running"] == 6
    assert result["group"]["logs"][0]["state"] == "collected"
    assert result["group"]["summary"]["members"][0]["health"] == "unhealthy"
    assert any(row["kind"] == "container" and row["data"]["health"] == "unhealthy" for row in result["observations"])
    answer = await ViewAssembler().build(
        DiagnosisProposal(summary="Healthcheck failed; cause is unknown", uncertain=True, evidence_ids=[], widgets=[]),
        context,
        "alice",
    )
    assert {widget.widget_type for widget in answer.widgets} == {"container_status", "log_anomalies"}
    assert not runtime.mutations


async def test_unavailable_inventory_preserves_unhealthy_member_log_coverage() -> None:
    class UnavailableInventory(GroupRuntime):
        """Retain a group observation while a later local inventory read fails."""

        async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
            """Report the failed local read without erasing observed group members."""
            raise DockSightError("runtime_unavailable", "Docker operation failed", 503)

    runtime = UnavailableInventory()
    runtime.rows = (replace(runtime.rows[0], state="running", exit_code=0, health="unhealthy"),)
    result = await DiagnosticTools(runtime, EvidenceContext(), "local").execute(
        ToolCall("group", "inspect_group", {"kind": "compose", "name": "infra"})
    )
    assert result["group"]["summary"]["running"] == 1
    assert result["group"]["logs"] == [
        {
            "container_id": "1" * 64,
            "name": "worker-1",
            "state": "not_collected",
            "evidence_id": None,
            "code": "runtime_unavailable",
        }
    ]


@pytest.mark.parametrize("health", ["starting", "healthy", None])
async def test_running_members_without_failure_signals_do_not_spend_the_group_log_budget(health: str | None) -> None:
    runtime = GroupRuntime()
    runtime.rows = (replace(runtime.rows[0], state="running", exit_code=0, restart_count=0, health=health),)
    result = await DiagnosticTools(runtime, EvidenceContext(), "local").execute(
        ToolCall("group", "inspect_group", {"kind": "compose", "name": "infra"})
    )
    assert not runtime.reads
    assert result["group"]["logs"] == []


@pytest.mark.parametrize("repair", [False, True])
async def test_healthy_group_final_and_repair_schemas_only_offer_cards_with_collected_data(repair: bool) -> None:
    """A group-only observation must not let constrained generation select an individual-container card."""
    runtime = GroupRuntime()
    runtime.rows = (replace(runtime.rows[0], state="running", exit_code=0, restart_count=0, health="healthy"),)
    answer = {
        "summary": "The project has one running, healthy container",
        "uncertain": False,
        "evidence_ids": ["e1"],
        "widgets": [{"widget_type": "compose_stack", "evidence_ids": ["e1"]}],
    }
    invalid = {**answer, "widgets": [{"widget_type": "container_status", "evidence_ids": ["e1"]}]}
    model = ScriptedModel(
        [ModelReply("Ready"), *([ModelReply(json.dumps(invalid))] if repair else []), ModelReply(json.dumps(answer))]
    )
    service = Diagnostics(runtime, model, MemorySessions(), Redactor())
    with patch.object(model, "complete", wraps=model.complete) as complete:
        events = [
            event
            async for event in service.stream(
                "alice",
                "local",
                "Show the current state of Compose project infra",
                group=GroupTarget(kind="compose", name="infra"),
            )
        ]
    assert events[-1]["type"] == "turn.completed"
    for call in complete.call_args_list[1:]:
        schema = call.kwargs["schema"]
        assert schema["$defs"]["WidgetProposal"]["properties"]["widget_type"]["enum"] == ["compose_stack"]
    report = next(event["answer"] for event in events if event["type"] == "answer.ready")
    assert report["group"]["summary"]["running"] == 1
    assert [card["widget_type"] for card in report["widgets"]] == ["compose_stack"]
    assert not runtime.reads and not runtime.mutations


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


async def test_plain_question_resolves_the_exact_compose_name_before_model_exploration() -> None:
    model = ScriptedModel(
        [
            ModelReply("Ready"),
            ModelReply(
                json.dumps(
                    {
                        "summary": "Several project members failed",
                        "uncertain": True,
                        "evidence_ids": ["e1"],
                        "widgets": [],
                    }
                )
            ),
        ]
    )
    events = [
        event
        async for event in Diagnostics(GroupRuntime(), model, MemorySessions(), Redactor()).stream(
            "alice", "local", "What happened to infra?"
        )
    ]
    answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
    assert answer["group"]["summary"]["name"] == "infra"
    assert len(answer["group"]["summary"]["members"]) == 6
    assert len(answer["widgets"]) == 7
    assert any("database unavailable" in message.content for message in model.requests[0][0] if message.role == "tool")
    assert events[-1]["type"] == "turn.completed"


async def test_evidence_ids_cannot_be_interpreted_as_docker_id_prefixes() -> None:
    context = EvidenceContext()
    tools = DiagnosticTools(FakeRuntime(), context, "local")
    await tools.execute(ToolCall("inventory", "list_containers", {}))
    with pytest.raises(DockSightError, match=r"data\.id or the exact container name"):
        await tools.execute(ToolCall("wrong", "inspect_container", {"container_id": "e1"}))
    with pytest.raises(DockSightError, match=r"data\.id or the exact container name"):
        await tools.execute(ToolCall("prefix", "inspect_container", {"container_id": "abcd"}))


@pytest.mark.parametrize("explicit", [False, True])
async def test_two_failed_members_keep_separate_cards_when_model_only_selects_the_last_one(explicit: bool) -> None:
    class TwoFailures(GroupRuntime):
        """Represent independent backend and monitoring failures in one observed Compose project."""

        def __init__(self) -> None:
            """Keep two failures with distinct exact identities and source content."""
            super().__init__()
            self.rows = tuple(
                replace(row, name=name, compose_project="vintoria-infra")
                for row, name in zip(self.rows[:2], ("backend-1", "grafana-1"), strict=True)
            )

        async def stacks(self, host: str, kind: str) -> tuple[StackSummary, ...]:
            """Reuse observed member data under the canonical project label."""
            return tuple(replace(row, name="vintoria-infra", total=2) for row in await super().stacks(host, kind))

        async def logs(self, host: str, container_id: str, lines: int, max_bytes: int) -> LogBatch:
            """Return distinct sanitized facts for each exact requested resource."""
            return LogBatch((replace(self.log_batch.entries[0], message=container_id[:1] + " failure"),))

    model = ScriptedModel(
        [
            ModelReply("Ready"),
            ModelReply(
                json.dumps(
                    {
                        "summary": "The monitoring container failed",
                        "uncertain": True,
                        "evidence_ids": ["e5"],
                        "widgets": [
                            {"widget_type": "container_status", "evidence_ids": ["e1", "e4"]},
                            {"widget_type": "log_anomalies", "evidence_ids": ["e5"]},
                        ],
                    }
                )
            ),
        ]
    )
    events = [
        event
        async for event in Diagnostics(TwoFailures(), model, MemorySessions(), Redactor()).stream(
            "alice",
            "local",
            "Check vintoria-infta?",
            group=GroupTarget(kind="compose", name="vintoria-infra") if explicit else None,
        )
    ]
    assert events[-1]["type"] == "turn.completed"
    answer = next(event["answer"] for event in events if event["type"] == "answer.ready")
    assert answer["group"]["summary"]["total"] == 2
    assert answer["group"]["summary"]["running"] == 0
    assert len(answer["widgets"]) == 4
    states = {
        row["snapshot"]["name"]: row["snapshot"]
        for row in answer["widgets"]
        if row["widget_type"] == "container_status"
    }
    assert set(states) == {"backend-1", "grafana-1"}
    assert (states["backend-1"]["state"], states["backend-1"]["exit_code"]) == ("exited", 1)
    assert (states["grafana-1"]["state"], states["grafana-1"]["exit_code"]) == ("exited", 1)
    logs = [row for row in answer["widgets"] if row["widget_type"] == "log_anomalies"]
    assert {(row["container_id"], row["logs"]["entries"][0]["message"]) for row in logs} == {
        ("1" * 64, "1 failure"),
        ("2" * 64, "2 failure"),
    }


async def test_scope_clarification_finishes_its_tool_progress_without_calling_the_model() -> None:
    runtime = GroupRuntime()
    runtime.item = replace(runtime.item, name="infra")
    model = ScriptedModel([])
    events = [
        event
        async for event in Diagnostics(runtime, model, MemorySessions(), Redactor()).stream(
            "alice", "local", "What happened to infra?"
        )
    ]
    assert events[-1]["type"] == "turn.completed"
    assert any(event["type"] == "clarification.required" for event in events)
    assert any(
        event["type"] == "tool.completed" and event["tool"] == "resolve_target" and event["ok"] for event in events
    )
    assert not model.requests


async def test_scope_resolution_keeps_exact_containers_and_clarifies_an_ambiguous_group_name() -> None:
    runtime = GroupRuntime()
    exact = await resolve_target(runtime, "local", f"Investigate infra worker {runtime.rows[0].id}")
    assert exact.group is None
    named = await resolve_target(runtime, "local", "What happened to worker-1?")
    assert named.group is None
    runtime.item = replace(runtime.item, name="infra")
    ambiguous = await resolve_target(runtime, "local", "What happened to infra?")
    assert ambiguous.group is None and ambiguous.container_id is None
    assert ambiguous.selection is not None
    assert {row.kind for row in ambiguous.selection.candidates} == {"container", "compose"}


async def test_scope_resolution_does_not_match_a_project_name_inside_a_container_name() -> None:
    assert (await resolve_target(GroupRuntime(), "local", "Inspect infra-backend-1")).group is None


async def test_scope_resolution_discovers_a_named_swarm_stack() -> None:
    class SwarmRuntime(GroupRuntime):
        """Expose a manager stack without a local Compose project of the same name."""

        async def stacks(self, host: str, kind: str) -> tuple[StackSummary, ...]:
            """Return manager-owned stack metadata."""
            return (StackSummary("production", "swarm", 4, 2),)

    target = (await resolve_target(SwarmRuntime(), "local", "What happened to production?")).group
    assert target == GroupTarget(kind="swarm", name="production")


async def test_scope_resolution_respects_kind_and_sentence_punctuation() -> None:
    class DualRuntime(GroupRuntime):
        """Expose colliding Compose and Swarm names for disambiguation."""

        async def stacks(self, host: str, kind: str) -> tuple[StackSummary, ...]:
            """Return the namespace selected by the metadata read."""
            return (StackSummary("infra", "swarm", 4, 2),) if kind == "swarm" else await super().stacks(host, kind)

    assert (await resolve_target(DualRuntime(), "local", "Inspect the Swarm stack infra.")).group == GroupTarget(
        kind="swarm", name="infra"
    )
    assert (await resolve_target(DualRuntime(), "local", "Inspect the Compose project infra.")).group == GroupTarget(
        kind="compose", name="infra"
    )
    ambiguous = await resolve_target(DualRuntime(), "local", "What happened to infra?")
    assert ambiguous.group is None
    assert ambiguous.selection is not None
    assert len(ambiguous.selection.candidates) == 2
    assert (await resolve_target(GroupRuntime(), "local", "Diagnose infra.")).group == GroupTarget(
        kind="compose", name="infra"
    )


async def test_failed_optional_swarm_discovery_does_not_block_container_diagnostics() -> None:
    class FailedSwarm(GroupRuntime):
        """Keep ordinary Docker reads available while manager metadata fails."""

        async def stacks(self, host: str, kind: str) -> tuple[StackSummary, ...]:
            """Report a bounded manager read failure."""
            raise DockSightError("runtime_timeout", "Docker operation timed out", 504)

    model = ScriptedModel(
        [
            ModelReply("Ready"),
            ModelReply(
                json.dumps(
                    {
                        "summary": "More observations are needed",
                        "uncertain": True,
                        "evidence_ids": [],
                        "widgets": [],
                    }
                )
            ),
        ]
    )
    service = Diagnostics(FailedSwarm(), model, MemorySessions(), Redactor())
    events = [event async for event in service.stream("alice", "local", "Why are containers restarting?")]
    assert events[-1]["type"] == "turn.completed"
    assert any("Swarm discovery failed" in message.content for message in model.requests[0][0])
    failed = [event async for event in service.stream("alice", "local", "Inspect the Swarm stack infra")]
    assert failed[-1]["type"] == "turn.failed"
    assert failed[-1]["code"] == "runtime_timeout"
