from dataclasses import replace
from typing import Final, Literal, cast

from pydantic import Field, TypeAdapter, ValidationError

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.ports.models import ToolCall, ToolSpec
from docksight.application.ports.runtime import RuntimeReadPort
from docksight.application.views.schemas import Contract
from docksight.domain.diagnostics import JsonObject, JsonValue
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import ContainerSnapshot, LogBatch, StackSummary


class NoArgs(Contract):
    pass


class ContainerArgs(Contract):
    container_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")


class StackArgs(Contract):
    kind: Literal["compose", "swarm"] = "compose"


_TOOLS: Final[dict[str, tuple[type[Contract], str]]] = {
    "list_containers": (NoArgs, "List up to 32 container snapshots on the selected host"),
    "inspect_container": (ContainerArgs, "Inspect container state and exit/OOM evidence"),
    "get_container_logs": (ContainerArgs, "Read bounded sanitized logs"),
    "get_container_stats": (ContainerArgs, "Read current CPU and memory metrics"),
    "get_container_env": (
        ContainerArgs,
        "Read explicitly allowlisted non-secret environment values",
    ),
    "list_stacks": (StackArgs, "Read Compose groups or Swarm service summaries on a manager"),
}
_SNAPSHOT: Final = TypeAdapter(ContainerSnapshot)
_LOGS: Final = TypeAdapter(LogBatch)
_STACKS: Final = TypeAdapter(tuple[StackSummary, ...])


def tool_specs() -> tuple[ToolSpec, ...]:
    return tuple(
        ToolSpec(name, description, cast(JsonObject, schema.model_json_schema()))
        for name, (schema, description) in _TOOLS.items()
    )


class DiagnosticTools:
    def __init__(
        self,
        runtime: RuntimeReadPort,
        context: EvidenceContext,
        host: str,
        log_lines: int = 200,
        log_bytes: int = 65536,
    ) -> None:
        self.runtime = runtime
        self.context = context
        self.host = host
        self.log_lines = log_lines
        self.log_bytes = log_bytes

    async def execute(self, call: ToolCall) -> JsonObject:
        definition = _TOOLS.get(call.name)
        if definition is None:
            raise DockSightError("unknown_tool", "Tool is not allowed", 422)
        try:
            args = definition[0].model_validate(call.arguments)
        except ValidationError as exc:
            raise DockSightError(
                "invalid_tool_arguments", "Tool arguments do not match its schema", 422
            ) from exc
        if isinstance(args, NoArgs):
            rows = await self.runtime.containers(self.host)
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
        snapshot = await self.runtime.inspect(self.host, args.container_id)
        data = cast(JsonObject, _SNAPSHOT.dump_python(snapshot, mode="json"))
        if call.name == "get_container_stats":
            snapshot = replace(snapshot, metrics=await self.runtime.stats(self.host, snapshot.id))
            data = cast(JsonObject, _SNAPSHOT.dump_python(snapshot, mode="json"))
            item = self.context.record("stats", self.host, data, snapshot)
        elif call.name == "get_container_env":
            item = self.context.record(
                "env", self.host, {"variables": dict(snapshot.environment)}, snapshot
            )
        elif call.name == "get_container_logs":
            container = self.context.record("container", self.host, data, snapshot)
            logs = await self.runtime.logs(self.host, snapshot.id, self.log_lines, self.log_bytes)
            item = self.context.record(
                "logs",
                self.host,
                cast(JsonObject, _LOGS.dump_python(logs, mode="json")),
                snapshot,
                logs,
            )

            return {
                "evidence_id": item.id,
                "container_evidence_id": container.id,
                "data": item.data,
            }
        else:
            item = self.context.record("container", self.host, data, snapshot)

        return {"evidence_id": item.id, "data": item.data}
