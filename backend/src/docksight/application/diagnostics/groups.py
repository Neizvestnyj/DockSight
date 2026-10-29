import json
import re
from dataclasses import dataclass, replace
from typing import Final, Literal, cast

from pydantic import TypeAdapter

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.diagnostics.logs import fit_logs, log_data
from docksight.application.ports.runtime import RuntimeReadPort
from docksight.application.views.schemas import GroupInspection, GroupLogResult, GroupTarget
from docksight.domain.diagnostics import JsonObject, JsonValue
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import ContainerSnapshot, StackSummary

_STACKS: Final = TypeAdapter(tuple[StackSummary, ...])
_SNAPSHOT: Final = TypeAdapter(ContainerSnapshot)
MAX_GROUP_LOGS: Final = 4


@dataclass(frozen=True)
class TargetResolution:
    """Retain discovery snapshots and an unambiguous named group for one turn."""

    group: GroupTarget | None
    containers: tuple[ContainerSnapshot, ...]
    discovery_code: str | None = None


def _mentioned(query: str, name: str) -> bool:
    """Match an observed resource name without treating container-name prefixes as project references."""
    return re.search(r"(?<![\w.-])" + re.escape(name) + r"(?![\w-]|\.[\w-])", query, re.IGNORECASE) is not None


async def resolve_target(runtime: RuntimeReadPort, host: str, query: str) -> TargetResolution:
    """Resolve exact known names before model selection, preserving container targets and rejecting ambiguity."""
    rows = await runtime.containers(host)
    if any(row.id in query for row in rows):
        return TargetResolution(None, rows)
    named_container = any(_mentioned(query, row.name) for row in rows)
    kind = _requested_kind(query)
    targets = _compose_targets(rows, query) if kind != "swarm" else []
    code = None
    if kind != "compose" and (targets or not named_container):
        swarm, code = await _swarm_targets(runtime, host, query, kind == "swarm")
        targets.extend(swarm)
    return TargetResolution(_unambiguous_target(targets, named_container), rows, code)


def _unambiguous_target(targets: list[GroupTarget], named_container: bool) -> GroupTarget | None:
    """Require explicit selection when observed identities collide across resource types."""
    if len(targets) > 1 or (targets and named_container):
        raise DockSightError("ambiguous_target", "Resource name is ambiguous; select one group or exact container", 422)
    return targets[0] if targets else None


def _requested_kind(query: str) -> Literal["compose", "swarm"] | None:
    """Respect explicit technology names without treating the generic word stack as Swarm."""
    if re.search(r"\bcompose\b", query, re.IGNORECASE):
        return "compose"
    if re.search(r"\bswarm\b", query, re.IGNORECASE):
        return "swarm"
    return None


def _compose_targets(rows: tuple[ContainerSnapshot, ...], query: str) -> list[GroupTarget]:
    """Identify exact project-label references without inferring membership from name prefixes."""
    names = {row.compose_project for row in rows if row.compose_project and _mentioned(query, row.compose_project)}
    return [GroupTarget(kind="compose", name=name) for name in sorted(names)]


async def _swarm_targets(
    runtime: RuntimeReadPort, host: str, query: str, required: bool
) -> tuple[list[GroupTarget], str | None]:
    """Discover stack names on a manager while treating a non-Swarm engine as a supported ordinary host."""
    try:
        stacks = await runtime.stacks(host, "swarm")
    except DockSightError as exc:
        if required:
            raise
        return [], None if exc.code == "unsupported_operation" else exc.code
    return [
        GroupTarget(kind="swarm", name=row.name)
        for row in stacks
        if row.kind == "swarm" and _mentioned(query, row.name)
    ], None


async def inspect_group(
    runtime: RuntimeReadPort, context: EvidenceContext, host: str, target: GroupTarget, log_lines: int, log_bytes: int
) -> JsonObject:
    """Collect a whole group summary and bounded local failure logs, retaining partial failures."""
    groups = await runtime.stacks(host, target.kind)
    summary = next((row for row in groups if row.kind == target.kind and row.name == target.name), None)
    if summary is None:
        raise DockSightError("group_not_found", "Group not found on the selected host", 404)
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
        raise DockSightError("group_not_found", "No group has been inspected", 409)
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
    problems = [row for row in local if row.state != "running" or row.oom_killed or row.restart_count > 0]
    for index, snapshot in enumerate(problems):
        result = GroupLogResult(
            container_id=snapshot.id, name=snapshot.name, state="not_collected", code="group_log_limit"
        )
        if index < MAX_GROUP_LOGS:
            result = await _read_logs(runtime, context, snapshot, log_lines, log_bytes)
        report.logs.append(result)
    report.logs.extend(_missing_logs(report.summary, tuple(row.id for row in local), "not_in_local_inventory"))


def _missing_logs(summary: StackSummary, local_ids: tuple[str, ...], code: str) -> list[GroupLogResult]:
    """Describe unexamined Compose containers without inferring their deletion from bounded inventory."""
    return [
        GroupLogResult(container_id=row.id, name=row.name, state="not_collected", code=code)
        for row in summary.members
        if row.kind == "container" and row.state != "running" and row.id not in local_ids
    ]


async def _read_logs(
    runtime: RuntimeReadPort, context: EvidenceContext, snapshot: ContainerSnapshot, log_lines: int, log_bytes: int
) -> GroupLogResult:
    """Record exact-resource sources and report a failed read without replacing observed facts."""
    result = GroupLogResult(container_id=snapshot.id, name=snapshot.name, state="failed")
    try:
        context.record(
            "container", snapshot.host, cast(JsonObject, _SNAPSHOT.dump_python(snapshot, mode="json")), snapshot
        )
        batch = await runtime.logs(snapshot.host, snapshot.id, min(log_lines, 200), min(log_bytes, 4096))
        batch = fit_logs(batch, min(context.remaining_bytes, 8192))
        ref = context.record("logs", snapshot.host, log_data(batch), snapshot, batch)
    except DockSightError as exc:
        result.code = exc.code
        return result
    result.state = "collected"
    result.evidence_id = ref.id
    return result
