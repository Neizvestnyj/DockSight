import json
from dataclasses import replace
from typing import Final, cast

from pydantic import TypeAdapter

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.diagnostics.logs import collect_logs, needs_logs
from docksight.application.ports.runtime import RuntimeReadPort
from docksight.application.views.schemas import GroupInspection, GroupLogResult, GroupTarget
from docksight.domain.diagnostics import JsonObject, JsonValue
from docksight.domain.errors import DockSightError, ErrorKind
from docksight.domain.runtime import StackSummary

_STACKS: Final = TypeAdapter(tuple[StackSummary, ...])
MAX_GROUP_LOGS: Final = 4


async def inspect_group(
    runtime: RuntimeReadPort, context: EvidenceContext, host: str, target: GroupTarget, log_lines: int, log_bytes: int
) -> JsonObject:
    """Collect a whole group summary and bounded local failure logs, retaining partial failures."""
    groups = await runtime.stacks(host, target.kind)
    summary = next((row for row in groups if row.kind == target.kind and row.name == target.name), None)
    if summary is None:
        raise DockSightError("group_not_found", "Group not found on the selected host", ErrorKind.NOT_FOUND)
    summary = _bounded_summary(summary, min(context.remaining_bytes, 32768))
    data: JsonObject = {"stacks": cast(list[JsonValue], _STACKS.dump_python((summary,), mode="json"))}
    ref = context.record("stack", host, data, stacks=(summary,))
    report = GroupInspection(summary=summary, evidence_id=ref.id, logs=[])
    context.group = report
    await _collect_local(runtime, context, host, report, log_lines, log_bytes)
    return group_result(context)


def _bounded_summary(summary: StackSummary, budget: int) -> StackSummary:
    """Preserve total counts while explicitly clipping member previews to the evidence budget."""
    while len(
        json.dumps({"stacks": _STACKS.dump_python((summary,), mode="json")}, ensure_ascii=False).encode()
    ) > budget and (summary.members or summary.container_ids):
        summary = replace(
            summary,
            members=summary.members[: len(summary.members) // 2],
            container_ids=summary.container_ids[: len(summary.container_ids) // 2],
            truncated=True,
        )
    return summary


def group_result(context: EvidenceContext) -> JsonObject:
    """Give the model real collected observations, bounding repeated coverage metadata separately."""
    report = context.group
    if report is None:
        raise DockSightError("group_not_found", "No group has been inspected", ErrorKind.CONFLICT)
    projection = report.model_copy(deep=True)
    observations: list[JsonValue] = [
        {"evidence_id": row.id, "kind": row.kind, "container_id": row.container_id, "data": row.data}
        for row in context.evidence.values()
        if row.kind != "stack" and row.container_id in report.summary.container_ids
    ]
    result: JsonObject = {"group": cast(JsonObject, projection.model_dump(mode="json")), "observations": observations}
    while len(json.dumps(result, ensure_ascii=False).encode()) > 65536:
        if projection.summary.members or projection.summary.container_ids:
            projection.summary = replace(
                projection.summary,
                members=projection.summary.members[: len(projection.summary.members) // 2],
                container_ids=projection.summary.container_ids[: len(projection.summary.container_ids) // 2],
                truncated=True,
            )
        elif projection.logs:
            projection.logs = projection.logs[: len(projection.logs) // 2]
        else:
            observations = observations[: len(observations) // 2]
        result = {
            "group": cast(JsonObject, projection.model_dump(mode="json")),
            "observations": observations,
            "projection_truncated": True,
        }
    return result


async def _collect_local(
    runtime: RuntimeReadPort,
    context: EvidenceContext,
    host: str,
    report: GroupInspection,
    log_lines: int,
    log_bytes: int,
) -> None:
    """Keep group membership available when subsequent local reads fail or omit a member."""
    try:
        rows = await runtime.containers(host)
    except DockSightError as exc:
        report.inventory_code = exc.code
        report.logs = _missing_logs(report.summary, (), exc.code)
        return
    local = [row for row in rows if row.id in report.summary.container_ids]
    problems = [row for row in local if needs_logs(row)]
    for index, snapshot in enumerate(problems):
        result = GroupLogResult(
            container_id=snapshot.id, name=snapshot.name, state="not_collected", code="group_log_limit"
        )
        if index < MAX_GROUP_LOGS:
            result = await collect_logs(runtime, context, snapshot, log_lines, log_bytes)
        report.logs.append(result)
    report.logs.extend(_missing_logs(report.summary, tuple(row.id for row in local), "not_in_local_inventory"))


def _missing_logs(summary: StackSummary, local_ids: tuple[str, ...], code: str) -> list[GroupLogResult]:
    """Describe unexamined Compose containers without inferring their deletion from bounded inventory."""
    return [
        GroupLogResult(container_id=row.id, name=row.name, state="not_collected", code=code)
        for row in summary.members
        if row.kind == "container" and (row.state != "running" or row.health == "unhealthy") and row.id not in local_ids
    ]
