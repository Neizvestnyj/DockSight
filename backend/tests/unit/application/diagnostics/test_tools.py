import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.diagnostics.tools import DiagnosticTools
from docksight.application.ports.models import ToolCall
from docksight.application.views.schemas import GroupTarget
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import LogBatch, LogEntry
from tests.fakes import DiscoveryRuntime, FakeRuntime


async def test_bound_container_inventory_and_reads_cannot_return_to_the_previous_group() -> None:
    runtime = DiscoveryRuntime()
    context = EvidenceContext()
    tools = DiagnosticTools(runtime, context, "local", container_id="3" * 64)
    await tools.execute(ToolCall("inventory", "list_containers", {}))
    assert {row.container_id for row in context.evidence.values()} == {"3" * 64}
    for tool, arguments in [
        ("get_container_logs", {"container_id": "1" * 64}),
        ("inspect_container", {"container_id": "backend-1"}),
        ("inspect_group", {"kind": "compose", "name": "vintoria-infra"}),
        ("list_stacks", {"kind": "compose"}),
    ]:
        with pytest.raises(DockSightError) as failure:
            await tools.execute(ToolCall(tool, tool, arguments))
        assert failure.value.code == "resource_outside_container"
    assert not runtime.reads
    await tools.execute(ToolCall("logs", "get_container_logs", {"container_id": "unrelated-1"}))
    assert runtime.reads == ["3" * 64]


async def test_group_selection_rejects_invented_candidates_without_recording_evidence() -> None:
    context = EvidenceContext()
    target = GroupTarget(kind="compose", name="vintoria-infra")
    tools = DiagnosticTools(DiscoveryRuntime(), context, "local", candidates=(target,))
    with pytest.raises(DockSightError, match="observed group"):
        await tools.execute(
            ToolCall("invented", "request_group_selection", {"candidates": [{"kind": "compose", "name": "invented"}]})
        )
    assert context.selection is None
    assert not context.evidence


async def test_group_selection_cannot_override_an_explicit_scope() -> None:
    target = GroupTarget(kind="compose", name="vintoria-infra")
    context = EvidenceContext()
    tools = DiagnosticTools(DiscoveryRuntime(), context, "local", group=target, candidates=(target,))
    with pytest.raises(DockSightError) as failure:
        await tools.execute(ToolCall("choose", "request_group_selection", {"candidates": [target.model_dump()]}))
    assert failure.value.code == "scope_already_selected"
    assert context.selection is None


@pytest.mark.parametrize("exact", [False, True])
async def test_inferred_group_cannot_bypass_a_nearly_identical_observed_identity(exact: bool) -> None:
    runtime = DiscoveryRuntime()
    target = GroupTarget(kind="compose", name="vintoria-infra")
    sibling = GroupTarget(kind="compose", name="vintoria-infrb")
    context = EvidenceContext()
    tools = DiagnosticTools(
        runtime,
        context,
        "local",
        candidates=(target, sibling),
        query="Check vintoria-infra" if exact else "Что не так \u0441 винтория инфра?",
    )
    await tools.execute(ToolCall("group", "inspect_group", target.model_dump()))
    if exact:
        assert context.selection is None
        assert context.group is not None
        assert set(runtime.reads) == {"1" * 64, "2" * 64}
    else:
        assert context.selection is not None
        assert context.selection.candidates == [target, sibling]
        assert context.group is None
        assert not runtime.reads


@pytest.mark.parametrize(
    "candidates",
    [
        [],
        [{"kind": "compose", "name": "same"}] * 2,
        [{"kind": "compose", "name": f"project-{index}"} for index in range(33)],
        [{"kind": "compose", "name": "valid", "host": "other"}],
    ],
)
async def test_group_selection_rejects_unbounded_duplicate_or_cross_host_options(
    candidates: list[dict[str, str]],
) -> None:
    tools = DiagnosticTools(DiscoveryRuntime(), EvidenceContext(), "local")
    with pytest.raises(DockSightError) as failure:
        await tools.execute(ToolCall("choose", "request_group_selection", {"candidates": candidates}))
    assert failure.value.code == "invalid_tool_arguments"


@pytest.mark.parametrize("message", ["x" * 60000, '\\"\n' * 20000, "Ж😀" * 20000], ids=["long", "escaped", "unicode"])
@pytest.mark.parametrize("consumed", [0, 50000, 64000])
async def test_logs_fit_remaining_serialized_evidence_budget(message: str, consumed: int) -> None:
    runtime = FakeRuntime()
    runtime.log_batch = LogBatch(tuple(LogEntry(message[index : index + 300]) for index in range(0, len(message), 300)))
    context = EvidenceContext()
    context.record("env", "local", {"padding": "a" * consumed})
    result = await DiagnosticTools(runtime, context, "local").execute(
        ToolCall("logs", "get_container_logs", {"container_id": "worker"})
    )
    batch = context.logs[str(result["evidence_id"])]
    assert batch.truncated is True
    assert batch.entries
    assert batch.entries[0].message
    assert message.endswith(batch.entries[-1].message)
    assert context.used_bytes <= 65536
    assert context.used_bytes == sum(
        len(json.dumps(item.data, ensure_ascii=False).encode()) for item in context.evidence.values()
    )


async def test_short_logs_remain_complete() -> None:
    context = EvidenceContext()
    result = await DiagnosticTools(FakeRuntime(), context, "local").execute(
        ToolCall("logs", "get_container_logs", {"container_id": "worker"})
    )
    assert context.logs[str(result["evidence_id"])].truncated is False


async def test_exhausted_evidence_budget_rejects_logs_without_overspending() -> None:
    context = EvidenceContext()
    context.record("env", "local", {"padding": "a" * 65500})
    with pytest.raises(DockSightError) as error:
        await DiagnosticTools(FakeRuntime(), context, "local").execute(
            ToolCall("logs", "get_container_logs", {"container_id": "worker"})
        )
    assert error.value.code == "evidence_limit"
    assert context.used_bytes <= 65536


@pytest.mark.parametrize("reference", ["backend-1", "1" * 64])
async def test_repeated_read_reuses_observations_across_exact_name_and_id(reference: str) -> None:
    runtime = DiscoveryRuntime()
    context = EvidenceContext()
    tools = DiagnosticTools(runtime, context, "local")
    first = await tools.execute(ToolCall("first", "get_container_logs", {"container_id": "backend-1"}))
    runtime.log_batch = LogBatch((LogEntry("A later observation belongs to a new turn."),))
    with patch.object(runtime, "containers", side_effect=AssertionError("Repeated read requested fresh inventory")):
        repeated = await tools.execute(ToolCall("again", "get_container_logs", {"container_id": reference}))
    assert repeated == {"already_collected": True, "evidence_ids": ["e1", "e2"]}
    assert first["data"] != repeated.get("data")
    assert runtime.reads == ["1" * 64]
    assert len(context.evidence) == 2
    fresh = await DiagnosticTools(runtime, EvidenceContext(), "local").execute(
        ToolCall("new-turn", "get_container_logs", {"container_id": "backend-1"})
    )
    assert "A later observation" in json.dumps(fresh)
    assert runtime.reads == ["1" * 64, "1" * 64]


async def test_repeated_group_read_returns_only_its_existing_evidence_references() -> None:
    runtime = DiscoveryRuntime()
    context = EvidenceContext()
    tools = DiagnosticTools(runtime, context, "local")
    target = {"kind": "compose", "name": "vintoria-infra"}
    first = await tools.execute(ToolCall("first", "inspect_group", target))
    size = len(context.evidence)
    second = await tools.execute(ToolCall("second", "inspect_group", target))
    assert second == {"already_collected": True, "evidence_ids": [f"e{i}" for i in range(1, size + 1)]}
    assert "observations" in first
    assert len(context.evidence) == size
    assert len(json.dumps(second)) < len(json.dumps(first)) // 2
    assert runtime.reads == ["1" * 64, "2" * 64]


async def test_narrowed_scope_does_not_reuse_an_unscoped_inventory_or_outside_read() -> None:
    context = EvidenceContext()
    tools = DiagnosticTools(DiscoveryRuntime(), context, "local")
    await tools.execute(ToolCall("outside", "get_container_logs", {"container_id": "3" * 64}))
    await tools.execute(ToolCall("all", "list_containers", {}))
    await tools.execute(ToolCall("group", "inspect_group", {"kind": "compose", "name": "vintoria-infra"}))
    scoped = await tools.execute(ToolCall("scoped", "list_containers", {}))
    assert "already_collected" not in scoped
    assert "unrelated-1" not in json.dumps(scoped)
    with pytest.raises(DockSightError) as failure:
        await tools.execute(ToolCall("outside-again", "get_container_logs", {"container_id": "3" * 64}))
    assert failure.value.code == "resource_outside_group"


async def test_distinct_tools_and_arguments_collect_distinct_observations() -> None:
    context = EvidenceContext()
    tools = DiagnosticTools(DiscoveryRuntime(), context, "local")
    for tool, container in [
        ("inspect_container", "1" * 64),
        ("get_container_logs", "1" * 64),
        ("get_container_logs", "2" * 64),
    ]:
        result = await tools.execute(ToolCall(tool + container, tool, {"container_id": container}))
        assert "already_collected" not in result
    assert len(context.evidence) == 5


async def test_failed_read_can_be_corrected_without_reusing_its_error() -> None:
    class RecoveringRuntime(FakeRuntime):
        """Fail one external log read before a later successful observation."""

        async def logs(self, host: str, container_id: str, lines: int, max_bytes: int) -> LogBatch:
            """Use the existing fixture state to report temporary log unavailability."""
            if self.item.state == "exited":
                raise DockSightError("logs_unavailable", "Logs are temporarily unavailable", 503)
            return self.log_batch

    runtime = RecoveringRuntime()
    tools = DiagnosticTools(runtime, EvidenceContext(), "local")
    call = ToolCall("logs", "get_container_logs", {"container_id": "worker"})
    with pytest.raises(DockSightError, match="temporarily"):
        await tools.execute(call)
    runtime.item = replace(runtime.item, state="running")
    assert "data" in await tools.execute(call)
    with pytest.raises(DockSightError) as invalid:
        await tools.execute(ToolCall("invalid", "get_container_logs", {"container_id": "worker", "host": "other"}))
    assert invalid.value.code == "invalid_tool_arguments"
