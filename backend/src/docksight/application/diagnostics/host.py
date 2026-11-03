import json
from typing import Final, cast

from pydantic import ValidationError

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.diagnostics.logs import collect_logs, needs_logs
from docksight.application.ports.runtime import RuntimeReadPort
from docksight.application.views.schemas import GroupLogResult, GroupTarget, HostInspection, HostMember
from docksight.domain.diagnostics import JsonObject, JsonValue
from docksight.domain.errors import DockSightError, ErrorKind
from docksight.domain.runtime import ContainerSnapshot

MAX_HOST_LOGS: Final = 4
MAX_HOST_MEMBERS: Final = 32
MAX_MODEL_MEMBERS: Final = 8


def _priority(snapshot: ContainerSnapshot) -> tuple[int, str, str]:
    """Prefer concrete failure signals while retaining normally stopped containers as review candidates."""
    if snapshot.oom_killed or snapshot.health == "unhealthy" or snapshot.state in {"dead", "restarting"}:
        rank = 0
    elif snapshot.state == "exited" and snapshot.exit_code != 0:
        rank = 1
    elif snapshot.restart_count:
        rank = 2
    elif snapshot.state != "running":
        rank = 3
    else:
        rank = 4
    return rank, snapshot.name, snapshot.id


def _member(snapshot: ContainerSnapshot) -> HostMember:
    """Keep only contract-valid group choices while retaining the original container identity and observations."""
    group = None
    if snapshot.compose_project:
        try:
            group = GroupTarget(kind="compose", name=snapshot.compose_project)
        except ValidationError:
            pass
    return HostMember(
        container_id=snapshot.id,
        name=snapshot.name,
        state=snapshot.state,
        health=snapshot.health,
        exit_code=snapshot.exit_code,
        oom_killed=snapshot.oom_killed,
        restart_count=snapshot.restart_count,
        observed_at=snapshot.observed_at,
        group=group,
        attention=needs_logs(snapshot),
    )


def _targets(members: list[HostMember], candidates: tuple[GroupTarget, ...]) -> list[GroupTarget]:
    """Keep every displayed member's group selectable before filling other discovered scope choices."""
    result: list[GroupTarget] = []
    for row in [*(member.group for member in members if member.group), *candidates]:
        if row not in result:
            result.append(row)
    return result


def _metadata(report: HostInspection) -> JsonObject:
    """Serialize the overview independently of its assigned evidence reference and later log coverage."""
    return cast(JsonObject, report.model_dump(mode="json", exclude={"evidence_id", "logs"}))


def _bound(report: HostInspection, candidates: tuple[GroupTarget, ...], budget: int) -> None:
    """Make clipping explicit and retain counts for the complete observed, capped inventory."""
    while len(json.dumps(_metadata(report), ensure_ascii=False).encode()) > budget and report.members:
        report.members = report.members[: len(report.members) // 2]
        report.targets = _targets(report.members, candidates)[:32]
        report.truncated = True
    while len(json.dumps(_metadata(report), ensure_ascii=False).encode()) > budget and report.targets:
        report.targets = report.targets[: len(report.targets) // 2]
        report.truncated = True


async def inspect_host(
    runtime: RuntimeReadPort,
    context: EvidenceContext,
    host: str,
    inventory: tuple[ContainerSnapshot, ...],
    candidates: tuple[GroupTarget, ...],
    discovery_code: str | None,
    log_lines: int,
    log_bytes: int,
) -> JsonObject:
    """Collect one bounded local-host overview without choosing a project on the operator's behalf."""
    rows = tuple({row.id: row for row in inventory[:200]}.values())
    if any(row.host != host for row in rows):
        raise DockSightError("invalid_runtime_data", "Inventory is outside the selected host", ErrorKind.DEPENDENCY)
    ordered = sorted(rows, key=_priority)
    try:
        members = [_member(row) for row in ordered[:MAX_HOST_MEMBERS]]
    except ValidationError as exc:
        raise DockSightError(
            "invalid_runtime_data", "Invalid host inventory observation", ErrorKind.DEPENDENCY
        ) from exc
    targets = _targets(members, candidates)
    report = HostInspection(
        host=host,
        evidence_id="pending",
        total=len(rows),
        running=sum(row.state == "running" for row in rows),
        attention=sum(needs_logs(row) for row in rows),
        members=members,
        targets=targets[:32],
        logs=[],
        truncated=len(inventory) >= 200 or len(rows) > len(members) or len(targets) > 32,
        discovery_code=discovery_code,
    )
    _bound(report, candidates, min(context.remaining_bytes, 32768))
    ref = context.record("host", host, _metadata(report))
    report.evidence_id = ref.id
    context.host_overview = report
    await _collect(runtime, context, report, rows, log_lines, log_bytes)
    return host_result(context)


async def _collect(
    runtime: RuntimeReadPort,
    context: EvidenceContext,
    report: HostInspection,
    rows: tuple[ContainerSnapshot, ...],
    log_lines: int,
    log_bytes: int,
) -> None:
    """Spend a global four-read log budget only on displayed review candidates."""
    by_id = {row.id: row for row in rows}
    for member in report.members:
        if not member.attention:
            continue
        result = GroupLogResult(
            container_id=member.container_id, name=member.name, state="not_collected", code="host_log_limit"
        )
        if len(report.logs) < MAX_HOST_LOGS:
            result = await collect_logs(runtime, context, by_id[member.container_id], log_lines, log_bytes)
        report.logs.append(result)


def update_host_log(
    context: EvidenceContext, snapshot: ContainerSnapshot, evidence_id: str | None = None, code: str | None = None
) -> None:
    """Reconcile later log attempts for displayed members without expanding the bounded preview."""
    report = context.host_overview
    if report is None or not any(row.container_id == snapshot.id for row in report.members):
        return
    result = GroupLogResult(
        container_id=snapshot.id,
        name=snapshot.name,
        state="collected" if evidence_id else "failed",
        evidence_id=evidence_id,
        code=code,
    )
    for index, row in enumerate(report.logs):
        if row.container_id == snapshot.id:
            report.logs[index] = result
            return
    report.logs.append(result)


def _model_overview(report: HostInspection) -> JsonObject:
    """Limit repeated inventory detail in model context while the public report retains its full preview."""
    overview = cast(JsonObject, report.model_dump(mode="json"))
    members = report.members[:MAX_MODEL_MEMBERS]
    overview["members"] = [cast(JsonObject, row.model_dump(mode="json")) for row in members]
    visible = {row.container_id for row in members}
    overview["logs"] = [
        cast(JsonObject, row.model_dump(mode="json")) for row in report.logs if row.container_id in visible
    ]
    return overview


def host_result(context: EvidenceContext) -> JsonObject:
    """Give the model bounded observations and explicit projection coverage without copying hidden context."""
    report = context.host_overview
    if report is None:
        raise DockSightError("host_overview_missing", "No host overview has been collected", ErrorKind.CONFLICT)
    observations: list[JsonValue] = [
        {"evidence_id": row.id, "kind": row.kind, "container_id": row.container_id, "data": row.data}
        for row in context.evidence.values()
        if row.kind != "host" and row.host == report.host
    ]
    result: JsonObject = {"overview": _model_overview(report), "observations": observations}
    if len(report.members) > MAX_MODEL_MEMBERS:
        result["projection_truncated"] = True
    while len(json.dumps(result, ensure_ascii=False).encode()) > 65536 and observations:
        observations.pop()
        result["projection_truncated"] = True
    return result
