import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from copy import copy
from datetime import UTC, datetime
from functools import partial
from typing import Self, cast

from pydantic import ValidationError

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.diagnostics.lease import DiagnosticLease
from docksight.application.diagnostics.prompts import (
    SYSTEM_PROMPT,
    final_prompt,
    group_catalog,
    history_context,
    repair_feedback,
)
from docksight.application.diagnostics.scope import resolve_target
from docksight.application.diagnostics.tools import DiagnosticTools, tool_specs
from docksight.application.diagnostics.trace import DiagnosticTrace, schema_issues
from docksight.application.events import TurnEvent
from docksight.application.investigations.contracts import DiagnosticCommand
from docksight.application.ports.models import ModelMessage, ModelPort, ModelReply, ToolCall
from docksight.application.ports.runtime import RuntimeReadPort
from docksight.application.redaction import Redactor
from docksight.application.views.assembler import ViewAssembler
from docksight.application.views.registry import proposal_schema
from docksight.application.views.schemas import ContainerTarget, DiagnosisProposal, GroupTarget
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError, ErrorKind


async def _before_deadline[T](deadline: float, operation: Callable[[], Awaitable[T]]) -> T:
    """Keep the deadline across yields without keeping a task-bound timeout scope."""
    if asyncio.get_running_loop().time() >= deadline:
        raise TimeoutError
    async with asyncio.timeout_at(deadline):
        return await operation()


def _redact_narrative(proposal: DiagnosisProposal, redactor: Redactor) -> None:
    """Sanitize model-authored explanations before assembling bounded public recommendation text."""
    proposal.summary = redactor.text(proposal.summary)
    for card in proposal.widgets:
        if card.action_reason:
            card.action_reason = redactor.text(card.action_reason)[:240]
    if proposal.cause:
        proposal.cause.immediate = redactor.text(proposal.cause.immediate)
        if proposal.cause.underlying:
            proposal.cause.underlying = redactor.text(proposal.cause.underlying)
        proposal.cause.unknowns = [redactor.text(value) for value in proposal.cause.unknowns]


class Diagnostics:
    """Coordinate bounded fresh evidence and validated cards using caller-owned plain context."""

    def __init__(
        self,
        runtime: RuntimeReadPort,
        model: ModelPort,
        redactor: Redactor,
        assembler: ViewAssembler | None = None,
        max_model_calls: int = 6,
        max_tool_calls: int = 12,
        timeout: float = 180,
        log_lines: int = 200,
        log_bytes: int = 65536,
        concurrency: int = 4,
        model_identity: tuple[str, str] | None = None,
    ) -> None:
        """Bind ports and configure turn concurrency, budgets, and timeouts."""
        self.runtime = runtime
        self.model = model
        self.redactor = redactor
        self.assembler = assembler or ViewAssembler()
        self.max_model_calls = max_model_calls
        self.max_tool_calls = max_tool_calls
        self.timeout = timeout
        self.log_lines = log_lines
        self.log_bytes = log_bytes
        self._slots = asyncio.Semaphore(concurrency)
        self.model_identity = model_identity

    def with_model(self, model: ModelPort, identity: tuple[str, str]) -> Self:
        """Share actions, redaction, and global capacity with an immutable turn selection."""
        selected = copy(self)
        selected.model = model
        selected.model_identity = identity
        return selected

    async def reserve(self) -> DiagnosticLease:
        """Reserve shared diagnostic capacity before committing accepted work."""
        if self._slots.locked():
            raise DockSightError("turn_capacity", "Diagnostic capacity reached; retry later", ErrorKind.UNAVAILABLE)
        await self._slots.acquire()
        return DiagnosticLease(self, asyncio.get_running_loop().time() + self.timeout)

    def release(self) -> None:
        """Return one slot after its owning lease settles."""
        self._slots.release()

    async def run(self, command: DiagnosticCommand) -> AsyncGenerator[TurnEvent]:
        """Run a preallocated turn without mutable session history or an archive lease."""
        lease = await self.reserve()
        stream = lease.run(command)
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()
            await lease.close()

    async def run_reserved(self, command: DiagnosticCommand, deadline: float) -> AsyncGenerator[TurnEvent]:
        """Execute an owned reservation without acquiring shared capacity a second time."""
        trace = DiagnosticTrace(command.turn_id, self.redactor)
        group = command.target if isinstance(command.target, GroupTarget) else None
        container_id = command.target.id if isinstance(command.target, ContainerTarget) else None
        try:
            self._validate_turn(command.host, command.query, group, container_id)
            async for event in self._run_turn(command, deadline, trace, group, container_id):
                yield event
        except (TimeoutError, DockSightError) as exc:
            for event in trace.failed(exc):
                yield event

    def _validate_turn(self, host: str, query: str, group: GroupTarget | None, container_id: str | None) -> None:
        """Reject invalid scope and query size before collecting fresh runtime evidence."""
        if host not in {item.id for item in self.runtime.hosts()}:
            raise DockSightError("host_not_found", "Configured host not found", ErrorKind.NOT_FOUND)
        if not query.strip() or len(query) > 4000:
            raise DockSightError("invalid_query", "Query must contain 1-4000 characters", ErrorKind.VALIDATION)
        if group is not None and container_id is not None:
            raise DockSightError("invalid_target", "Choose either a group or an exact container", ErrorKind.VALIDATION)

    async def _run_turn(
        self,
        command: DiagnosticCommand,
        deadline: float,
        trace: DiagnosticTrace,
        group: GroupTarget | None,
        container_id: str | None,
    ) -> AsyncGenerator[TurnEvent]:
        """Collect fresh evidence without mutating any persistent or legacy session values."""
        query = command.query
        yield {"type": "turn.started", "turn_id": trace.turn_id, "session_id": command.investigation_id}
        yield {
            "type": "trace.started",
            "turn_id": trace.turn_id,
            "provider": command.identity.provider if command.identity else None,
            "model": command.identity.model if command.identity else None,
            "started_at": datetime.now(UTC).isoformat(),
        }
        messages = [
            ModelMessage("system", SYSTEM_PROMPT),
            *history_context(command.context),
            ModelMessage("user", self.redactor.text(query)),
        ]
        context = EvidenceContext()
        tools = DiagnosticTools(self.runtime, context, command.host, self.log_lines, self.log_bytes, group, query=query)
        if group is None:
            async for event in self._discover(query, tools, messages, deadline, trace, container_id):
                yield event
        call = self._selected_read(tools)
        if call:
            messages.append(ModelMessage("assistant", "", (call,)))
            async for event in self._record_tool(
                call, tools, messages, deadline, 0, trace, strict=tools.group is not None or tools.host_wide
            ):
                yield event
        async for event in self._explore(messages, tools, deadline, trace, int(call is not None)):
            yield event
        if context.selection:
            yield {
                "type": "clarification.required",
                "turn_id": trace.turn_id,
                "selection": cast(JsonObject, context.selection.model_dump(mode="json")),
            }
            yield {"type": "turn.completed", "turn_id": trace.turn_id}
            return
        async for event in self._answer_turn(query, messages, context, command.actor, deadline, trace):
            yield event
        yield {"type": "turn.completed", "turn_id": trace.turn_id}

    def _selected_read(self, tools: DiagnosticTools) -> ToolCall | None:
        """Collect bounded facts for an exact selected target before model explanations or follow-up decisions."""
        if tools.group:
            return ToolCall("selected-group", "inspect_group", tools.group.model_dump())
        if tools.context.container_id:
            return ToolCall("selected-container", "get_container_logs", {"container_id": tools.context.container_id})
        if tools.host_wide:
            return ToolCall("selected-host", "inspect_host", {})
        return None

    async def _answer_turn(
        self,
        query: str,
        messages: list[ModelMessage],
        context: EvidenceContext,
        actor: str,
        deadline: float,
        trace: DiagnosticTrace,
    ) -> AsyncGenerator[TurnEvent]:
        """Finalize a validated answer without mutating caller-owned history."""
        if messages[-1].role == "assistant" and not messages[-1].tool_calls:
            messages = messages[:-1]
        messages.append(ModelMessage("user", final_prompt(self.redactor.text(query), context)))
        async for event in self._finalize(messages, context, actor, deadline, trace):
            yield event

    async def _discover(
        self,
        query: str,
        tools: DiagnosticTools,
        messages: list[ModelMessage],
        deadline: float,
        trace: DiagnosticTrace,
        container_id: str | None = None,
    ) -> AsyncGenerator[TurnEvent]:
        """Retain discovered identities and expose group choices before model-selected evidence reads."""
        yield {"type": "tool.started", "turn_id": trace.turn_id, "tool": "resolve_target"}
        yield trace.begin("tool", "resolve_target")
        resolved = await _before_deadline(
            deadline, lambda: resolve_target(self.runtime, tools.host, query, container_id)
        )
        tools.inventory, tools.group, tools.candidates = resolved.containers, resolved.group, resolved.candidates
        tools.context.container_id = resolved.container_id
        tools.context.selection = resolved.selection
        tools.host_wide, tools.discovery_code = resolved.host_wide, resolved.discovery_code
        yield trace.finish(code=resolved.discovery_code)
        yield {
            "type": "tool.completed",
            "turn_id": trace.turn_id,
            "tool": "resolve_target",
            "ok": resolved.discovery_code is None,
        }
        if resolved.discovery_code:
            messages.append(
                ModelMessage(
                    "system",
                    "Swarm discovery failed. Its stack inventory is unknown; "
                    "do not infer absence. Container observations remain usable.",
                )
            )
        if tools.context.container_id:
            messages.append(
                ModelMessage(
                    "system",
                    json.dumps(
                        {
                            "selected_container_id": tools.context.container_id,
                            "instruction": "This turn explicitly targets this observed container. "
                            "Earlier group conclusions are conversation context only. "
                            "Collect its fresh state and logs; do not return to the previous group.",
                        }
                    ),
                )
            )
        elif tools.host_wide:
            messages.append(
                ModelMessage(
                    "system",
                    "This turn covers the selected host, across observed projects and "
                    "ungrouped containers. Explain the host overview before the operator narrows "
                    "scope in a new turn; do not replace it with a group choice.",
                )
            )
        elif tools.group is None and tools.candidates:
            messages.append(ModelMessage("system", group_catalog(tools.candidates)))

    async def _explore(
        self,
        messages: list[ModelMessage],
        tools: DiagnosticTools,
        deadline: float,
        trace: DiagnosticTrace,
        used: int = 0,
    ) -> AsyncGenerator[TurnEvent]:
        """Collect evidence within shared model, tool, and wall-clock budgets."""
        if tools.context.selection:
            return
        tool_calls = used
        for _ in range(self.max_model_calls - 2):
            yield trace.begin("model", "collect_evidence")
            reply = await _before_deadline(deadline, lambda: self.model.complete(messages, tool_specs()))
            yield trace.finish(reply=reply)
            messages.append(ModelMessage("assistant", reply.content, reply.tool_calls, native=reply.native))
            if self._exploration_complete(reply, tools, messages):
                break
            reused = tools.reused_reads
            async for event in self._tool_batch(reply.tool_calls, tools, messages, deadline, tool_calls, trace):
                yield event
            tool_calls += len(reply.tool_calls)
            if (
                tools.context.selection
                or tool_calls >= self.max_tool_calls
                or (reply.tool_calls and tools.reused_reads - reused == len(reply.tool_calls))
            ):
                break

    def _exploration_complete(self, reply: ModelReply, tools: DiagnosticTools, messages: list[ModelMessage]) -> bool:
        """Keep prose-only clarification from skipping evidence collection within the existing model budget."""
        if reply.tool_calls:
            return False
        if tools.context.evidence or not any(row.name in reply.content for row in tools.candidates):
            return True
        messages.append(
            ModelMessage(
                "system",
                "No runtime evidence has been collected. Resolve the operator's group using a tool call: "
                "inspect_group for the one plausible catalog identity, or request_group_selection for plausible "
                "alternatives. Transliteration and spaces are allowed interpretations; an unrelated catalog name "
                "is not an alternative merely because it exists. "
                "Do not ask for confirmation in prose or invent evidence.",
            )
        )
        return False

    async def _tool_batch(
        self,
        calls: tuple[ToolCall, ...],
        tools: DiagnosticTools,
        messages: list[ModelMessage],
        deadline: float,
        used: int,
        trace: DiagnosticTrace,
    ) -> AsyncGenerator[TurnEvent]:
        """Stop a reply's remaining reads as soon as the operator must clarify its scope."""
        for offset, call in enumerate(calls):
            async for event in self._record_tool(call, tools, messages, deadline, used + offset, trace):
                yield event
            if tools.context.selection:
                return

    async def _record_tool(
        self,
        call: ToolCall,
        tools: DiagnosticTools,
        messages: list[ModelMessage],
        deadline: float,
        used: int,
        trace: DiagnosticTrace,
        strict: bool = False,
    ) -> AsyncGenerator[TurnEvent]:
        """Pair every selected call with a result, tracing only calls within the execution budget."""
        name = self.redactor.text(call.name)
        yield {"type": "tool.started", "turn_id": trace.turn_id, "tool": name}
        traced = used < self.max_tool_calls
        if traced:
            approved = {tool.name for tool in tool_specs()}
            yield trace.begin("tool", call.name if call.name in approved else "unapproved_tool")
        result = await self._tool_result(call, tools, deadline, used)
        if traced:
            error = result.get("error")
            yield trace.finish(code=error if isinstance(error, str) else None)
        messages.append(
            ModelMessage("tool", json.dumps(result, ensure_ascii=False), tool_call_id=call.id, tool_name=call.name)
        )
        yield {"type": "tool.completed", "turn_id": trace.turn_id, "tool": name, "ok": "error" not in result}
        if strict and isinstance(result.get("error"), str):
            raise DockSightError(str(result["error"]), "Selected scope could not be inspected", ErrorKind.DEPENDENCY)

    async def _tool_result(self, call: ToolCall, tools: DiagnosticTools, deadline: float, used: int) -> JsonObject:
        """Return a safe tool result while preserving the absolute turn deadline."""
        try:
            if used >= self.max_tool_calls:
                raise DockSightError("tool_limit", "Tool budget exhausted", ErrorKind.CONFLICT)
            return await _before_deadline(deadline, lambda: tools.execute(call))
        except DockSightError as exc:
            return {"error": exc.code, "message": exc.message}

    async def _finalize(
        self,
        messages: list[ModelMessage],
        context: EvidenceContext,
        actor: str,
        deadline: float,
        trace: DiagnosticTrace,
    ) -> AsyncGenerator[TurnEvent]:
        """Validate the final proposal and allow one budgeted schema or evidence repair."""
        instruction = messages[-1].content
        for attempt in range(2):
            yield trace.begin("model", "repair_response" if attempt else "final_response")
            reply = await _before_deadline(
                deadline, lambda: self.model.complete(messages, schema=proposal_schema(context))
            )
            yield trace.finish(reply=reply, preview=True)
            yield trace.begin("validation", "validate_diagnosis")
            try:
                if reply.tool_calls:
                    raise DockSightError(
                        "invalid_model_response", "Final response must not call tools", ErrorKind.DEPENDENCY
                    )
                proposal = DiagnosisProposal.model_validate_json(reply.content)
                _redact_narrative(proposal, self.redactor)

                answer = await _before_deadline(deadline, partial(self.assembler.build, proposal, context, actor))
            except (ValidationError, DockSightError) as exc:
                yield trace.finish(
                    code="invalid_schema" if isinstance(exc, ValidationError) else exc.code,
                    issues=schema_issues(exc) if isinstance(exc, ValidationError) else [],
                )
                if attempt:
                    raise DockSightError(
                        "invalid_diagnosis",
                        "Model could not produce a valid evidence-backed diagnosis",
                        ErrorKind.DEPENDENCY,
                    ) from exc
                messages.extend(
                    [
                        ModelMessage("assistant", reply.content),
                        ModelMessage("user", repair_feedback(exc, context, instruction)),
                    ]
                )
                continue
            yield trace.finish()
            yield {
                "type": "answer.ready",
                "turn_id": trace.turn_id,
                "answer": cast(JsonObject, answer.model_dump(mode="json")),
            }
            return
