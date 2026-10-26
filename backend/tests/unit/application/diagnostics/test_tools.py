import json

import pytest

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.diagnostics.tools import DiagnosticTools
from docksight.application.ports.models import ToolCall
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import LogBatch, LogEntry
from tests.fakes import FakeRuntime


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
    assert message.startswith(batch.entries[0].message)
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
