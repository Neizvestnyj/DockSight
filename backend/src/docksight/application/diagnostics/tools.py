import re
from dataclasses import replace
from typing import Final, Literal, cast

from pydantic import Field, TypeAdapter, ValidationError

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.diagnostics.groups import group_result, inspect_group
from docksight.application.diagnostics.host import host_result, inspect_host, update_host_log
from docksight.application.diagnostics.logs import fit_logs, log_data
from docksight.application.diagnostics.scope import group_alternatives
from docksight.application.ports.models import ToolCall, ToolSpec
from docksight.application.ports.runtime import RuntimeReadPort
from docksight.application.views.schemas import Contract, GroupSelection, GroupTarget, TargetSelection
from docksight.domain.diagnostics import JsonObject, JsonValue
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import ContainerSnapshot, StackSummary


class NoArgs(Contract):
    """Reject arguments for tools that need only the selected host."""

    pass


class ContainerArgs(Contract):
    """Validate a Docker container identifier without accepting a host override."""

    container_id: str = Field(
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$",
        description="Use the full data.id or exact observed container name, never an evidence_id.",
    )


class StackArgs(Contract):
    """Select Compose grouping or manager-only Swarm service reads."""

    kind: Literal["compose", "swarm"] = "compose"


_TOOLS: Final[dict[str, tuple[type[Contract], str]]] = {
    "inspect_host": (NoArgs, "Inspect this host across projects and ungrouped containers with bounded problem logs"),
    "list_containers": (NoArgs, "List up to 32 container snapshots on the selected host"),
    "inspect_container": (ContainerArgs, "Inspect process state, healthcheck status, and exit/OOM evidence"),
    "get_container_logs": (ContainerArgs, "Read bounded sanitized logs"),
    "get_container_stats": (ContainerArgs, "Read current CPU and memory metrics"),
    "get_container_env": (
        ContainerArgs,
        "Read explicitly allowlisted non-secret environment values",
    ),
    "list_stacks": (StackArgs, "Read Compose groups or Swarm service summaries on a manager"),
    "inspect_group": (GroupTarget, "Inspect a complete Compose project or Swarm stack and bounded local failure logs"),
    "request_group_selection": (
        GroupSelection,
        "Ask the operator to choose between plausible observed group candidates",
    ),
}
_SNAPSHOT: Final = TypeAdapter(ContainerSnapshot)
_STACKS: Final = TypeAdapter(tuple[StackSummary, ...])


def tool_specs() -> tuple[ToolSpec, ...]:
    """Expose schemas for the read-only diagnostic tool allowlist."""
    return tuple(
        ToolSpec(name, description, cast(JsonObject, schema.model_json_schema()))
        for name, (schema, description) in _TOOLS.items()
    )


class DiagnosticTools:
    """Validate model tool calls and record evidence on the selected host."""

    def __init__(
        self,
        runtime: RuntimeReadPort,
        context: EvidenceContext,
        host: str,
        log_lines: int = 200,
        log_bytes: int = 65536,
        group: GroupTarget | None = None,
        inventory: tuple[ContainerSnapshot, ...] | None = None,
        candidates: tuple[GroupTarget, ...] = (),
        query: str = "",
        container_id: str | None = None,
    ) -> None:
        """Bind one host, evidence context, and bounded log read settings."""
        self.runtime = runtime
        self.context = context
        self.host = host
        self.log_lines = log_lines
        self.log_bytes = log_bytes
        self.group = group
        self.inventory = inventory
        self.candidates = candidates
        self.query = query
        self.context.container_id = container_id
        self.host_wide = False
        self.discovery_code: str | None = None

    async def execute(self, call: ToolCall) -> JsonObject:
        """Reject unknown tools or arguments before dispatching a bounded runtime read."""
        definition = _TOOLS.get(call.name)
        if definition is None:
            raise DockSightError("unknown_tool", "Tool is not allowed", 422)
        try:
            args = definition[0].model_validate(call.arguments)
        except ValidationError as exc:
            raise DockSightError("invalid_tool_arguments", "Tool arguments do not match its schema", 422) from exc
        self._require_container_scope(args)
        if isinstance(args, GroupSelection):
            return self._selection(args)
        if isinstance(args, GroupTarget):
            return await self._group(args)
        if isinstance(args, NoArgs):
            return await self._host() if call.name == "inspect_host" else await self._containers()
        if isinstance(args, StackArgs):
            stacks = await self.runtime.stacks(self.host, args.kind)
            item = self.context.record(
                "stack",
                self.host,
                {"stacks": cast(list[JsonValue], _STACKS.dump_python(stacks, mode="json"))},
                stacks=stacks,
            )

            return {"evidence_id": item.id, "data": item.data}
        assert isinstance(args, ContainerArgs)
        return await self._container(call.name, args.container_id)

    def _require_container_scope(self, args: Contract) -> None:
        """Prevent model proposals from replacing an explicitly selected container with a previous group."""
        if self.context.container_id and isinstance(args, (GroupTarget, GroupSelection, StackArgs)):
            raise DockSightError("resource_outside_container", "Resource is outside the selected container", 422)

    def _selection(self, selection: GroupSelection) -> JsonObject:
        """Resolve model-proposed options back to server-discovered identities without reading container evidence."""
        if self.group or self.context.group or self.host_wide or self.context.host_overview:
            raise DockSightError("scope_already_selected", "A diagnostic scope is already selected for this turn", 409)
        if any(row not in self.candidates for row in selection.candidates):
            raise DockSightError("invalid_group_candidate", "Selection requires an observed group on this host", 422)
        self.context.selection = TargetSelection(
            candidates=[row for row in self.candidates if row in selection.candidates]
        )
        return cast(JsonObject, self.context.selection.model_dump(mode="json"))

    async def _containers(self) -> JsonObject:
        """Record bounded inventory and report truncation when evidence capacity is reached."""
        rows = await self._inventory()
        results: list[JsonValue] = []
        for snapshot in rows[:32]:
            try:
                item = self.context.record(
                    "container",
                    self.host,
                    cast(JsonObject, _SNAPSHOT.dump_python(snapshot, mode="json")),
                    snapshot,
                )
            except DockSightError as exc:
                if exc.code != "evidence_limit":
                    raise
                break
            results.append({"evidence_id": item.id, "data": item.data})
        return {"containers": results, "truncated": len(results) < len(rows)}

    async def _inventory(self) -> tuple[ContainerSnapshot, ...]:
        """Reuse this turn's discovery snapshots and keep any group read scoped before applying limits."""
        rows = self.inventory if self.inventory is not None else await self.runtime.containers(self.host)
        if self.context.container_id:
            rows = tuple(row for row in rows if row.id == self.context.container_id)
        if self.context.group:
            rows = tuple(row for row in rows if row.id in self.context.group.summary.container_ids)
        return rows

    async def _host(self) -> JsonObject:
        """Keep a host-wide report independent of group and container target selection."""
        if self.context.container_id:
            raise DockSightError("resource_outside_container", "Host overview is outside the selected container", 422)
        if self.group or self.context.group:
            raise DockSightError("resource_outside_group", "Host overview is outside the selected group", 422)
        if self.context.host_overview:
            return host_result(self.context)
        return await inspect_host(
            self.runtime,
            self.context,
            self.host,
            await self._inventory(),
            self.candidates,
            self.discovery_code,
            self.log_lines,
            self.log_bytes,
        )

    async def _group(self, target: GroupTarget) -> JsonObject:
        """Bind model-discovered groups and reuse an already collected report within this turn."""
        if self.context.host_overview or self.host_wide:
            raise DockSightError("scope_already_selected", "Narrow this host overview in a separate turn", 409)
        if self.group and target != self.group:
            raise DockSightError("resource_outside_group", "Resource is outside the selected group", 422)
        if self.context.group:
            current = self.context.group.summary
            if (target.kind, target.name) != (current.kind, current.name):
                raise DockSightError("resource_outside_group", "Resource is outside the selected group", 422)
            return group_result(self.context)
        alternatives = group_alternatives(target, self.candidates, self.query)
        if self.group is None and alternatives:
            return self._selection(alternatives)
        return await inspect_group(self.runtime, self.context, self.host, target, self.log_lines, self.log_bytes)

    async def _container(self, tool: str, container_id: str) -> JsonObject:
        """Resolve one container before collecting its allowlisted evidence."""
        exact_id = await self._resource_id(container_id)
        snapshot = await self.runtime.inspect(self.host, exact_id)
        if self.context.group and snapshot.id not in self.context.group.summary.container_ids:
            raise DockSightError("resource_outside_group", "Resource is outside the selected group", 422)
        data = cast(JsonObject, _SNAPSHOT.dump_python(snapshot, mode="json"))
        if tool == "get_container_stats":
            snapshot = replace(snapshot, metrics=await self.runtime.stats(self.host, snapshot.id))
            data = cast(JsonObject, _SNAPSHOT.dump_python(snapshot, mode="json"))
            item = self.context.record("stats", self.host, data, snapshot)
        elif tool == "get_container_env":
            item = self.context.record("env", self.host, {"variables": dict(snapshot.environment)}, snapshot)
        elif tool == "get_container_logs":
            return await self._logs(snapshot, data)
        else:
            item = self.context.record("container", self.host, data, snapshot)

        return {"evidence_id": item.id, "data": item.data}

    async def _logs(self, snapshot: ContainerSnapshot, data: JsonObject) -> JsonObject:
        """Retain exact-container observations and update host coverage after later log attempts."""
        container = self.context.record("container", self.host, data, snapshot)
        try:
            logs = await self.runtime.logs(self.host, snapshot.id, self.log_lines, self.log_bytes)
            logs = fit_logs(logs, self.context.remaining_bytes)
            item = self.context.record(
                "logs",
                self.host,
                log_data(logs),
                snapshot,
                logs,
            )
        except DockSightError as exc:
            update_host_log(self.context, snapshot, code=exc.code)
            raise
        update_host_log(self.context, snapshot, evidence_id=item.id)
        return {"evidence_id": item.id, "container_evidence_id": container.id, "data": item.data}

    async def _resource_id(self, value: str) -> str:
        """Accept full Docker IDs or discovered exact names, never arbitrary ID prefixes or evidence aliases."""
        if re.fullmatch(r"[a-f0-9]{64}", value):
            return self._bound_id(value)
        rows = self.inventory if self.inventory is not None else await self.runtime.containers(self.host)
        target = next((row for row in rows if row.name == value), None)
        if target:
            return self._bound_id(target.id)
        raise DockSightError(
            "invalid_resource_reference", "Use data.id or the exact container name, not evidence_id", 422
        )

    def _bound_id(self, container_id: str) -> str:
        """Validate exact container scope before a model-selected runtime read can occur."""
        if self.context.container_id and container_id != self.context.container_id:
            raise DockSightError("resource_outside_container", "Resource is outside the selected container", 422)
        return container_id
