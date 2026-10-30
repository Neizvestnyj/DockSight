import json

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
