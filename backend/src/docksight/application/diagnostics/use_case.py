import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import UTC, datetime
from functools import partial
from typing import cast
from uuid import uuid4

from pydantic import ValidationError

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.diagnostics.prompts import SYSTEM_PROMPT, final_prompt
from docksight.application.diagnostics.scope import resolve_target
from docksight.application.diagnostics.tools import DiagnosticTools, tool_specs
from docksight.application.diagnostics.trace import DiagnosticTrace, schema_issues
from docksight.application.events import TurnEvent
from docksight.application.ports.models import ModelMessage, ModelPort, ToolCall
from docksight.application.ports.runtime import RuntimeReadPort
from docksight.application.ports.state import Session, SessionStore
from docksight.application.redaction import Redactor
from docksight.application.views.assembler import ViewAssembler
from docksight.application.views.registry import proposal_schema
from docksight.application.views.schemas import DiagnosisProposal, GroupTarget
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError


async def _before_deadline[T](deadline: float, operation: Callable[[], Awaitable[T]]) -> T:
    """Keep the deadline across yields without keeping a task-bound timeout scope."""
    if asyncio.get_running_loop().time() >= deadline:
        raise TimeoutError
    async with asyncio.timeout_at(deadline):
        return await operation()


def _repair_feedback(error: ValidationError | DockSightError, context: EvidenceContext, instruction: str) -> str:
    """Explain validation failures with field locations and trusted evidence groups, without raw values."""
    failure: dict[str, object]
    if isinstance(error, ValidationError):
        failure = {"code": "invalid_schema", "issues": [issue.model_dump() for issue in schema_issues(error)]}
    else:
        failure = {"code": error.code, "message": error.message}
    groups: dict[tuple[str, str], list[str]] = {}
    for ref, snapshot in context.snapshots.items():
        groups.setdefault((snapshot.host, snapshot.id), []).append(ref)
    return json.dumps(
        {
            "instruction": instruction
            + "\nCorrect the reported error. Each container evidence group is one container.",
            "error": failure,
            "evidence_ids": list(context.evidence),
            "container_evidence_groups": list(groups.values()),
            "log_evidence_ids": list(context.logs),
            "stack_evidence_ids": list(context.stacks),
        }
    )


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
    """Coordinate bounded evidence collection, validated cards, and session history."""

    def __init__(
        self,
        runtime: RuntimeReadPort,
        model: ModelPort,
        sessions: SessionStore,
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
        self.sessions = sessions
        self.redactor = redactor
        self.assembler = assembler or ViewAssembler()
        self.max_model_calls = max_model_calls
        self.max_tool_calls = max_tool_calls
        self.timeout = timeout
        self.log_lines = log_lines
        self.log_bytes = log_bytes
        self._slots = asyncio.Semaphore(concurrency)
        self.model_identity = model_identity

    async def stream(
        self, actor: str, host: str, query: str, session_id: str | None = None, group: GroupTarget | None = None
    ) -> AsyncGenerator[TurnEvent]:
        """Lease a scoped session and emit one terminal event for a bounded turn."""
        turn_id = str(uuid4())
        trace = DiagnosticTrace(turn_id, self.redactor)
        deadline = asyncio.get_running_loop().time() + self.timeout
        try:
            self._validate_turn(host, query)
            async with (
                self._slots,
                self.sessions.lease(session_id, actor, host) as session,
            ):
                async for event in self._run_turn(session, query, deadline, trace, group):
                    yield event
        except (TimeoutError, DockSightError) as exc:
            code, message = (
                (exc.code, exc.message)
                if isinstance(exc, DockSightError)
                else ("turn_timeout", "Diagnostic turn timed out")
            )
            if trace.active:
                if trace.active.kind == "tool":
                    yield {"type": "tool.completed", "turn_id": turn_id, "tool": trace.active.operation, "ok": False}
                yield trace.finish(code=code)
            yield {
                "type": "turn.failed",
                "turn_id": turn_id,
                "code": code,
                "message": message,
            }

    def _validate_turn(self, host: str, query: str) -> None:
        """Reject invalid scope, query size, or exhausted capacity before leasing a session."""
        if host not in {item.id for item in self.runtime.hosts()}:
            raise DockSightError("host_not_found", "Configured host not found", 404)
        if not query.strip() or len(query) > 4000:
            raise DockSightError("invalid_query", "Query must contain 1-4000 characters", 422)
        if self._slots.locked():
            raise DockSightError("turn_capacity", "Diagnostic capacity reached; retry later", 503)

    async def _run_turn(
        self, session: Session, query: str, deadline: float, trace: DiagnosticTrace, group: GroupTarget | None
    ) -> AsyncGenerator[TurnEvent]:
        """Collect fresh evidence and retain only the validated summary in session history."""
        yield {"type": "turn.started", "turn_id": trace.turn_id, "session_id": session.id}
        yield {
            "type": "trace.started",
            "turn_id": trace.turn_id,
            "provider": self.model_identity[0] if self.model_identity else None,
            "model": self.model_identity[1] if self.model_identity else None,
            "started_at": datetime.now(UTC).isoformat(),
        }
        messages = [
            ModelMessage("system", SYSTEM_PROMPT),
            *session.history,
            ModelMessage("user", self.redactor.text(query)),
        ]
        context = EvidenceContext()
        inventory = None
        if group is None:
            yield {"type": "tool.started", "turn_id": trace.turn_id, "tool": "resolve_target"}
            yield trace.begin("tool", "resolve_target")
            resolved = await _before_deadline(deadline, lambda: resolve_target(self.runtime, session.host, query))
            inventory, group = resolved.containers, resolved.group
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
                        "Swarm discovery failed. Its stack inventory is unknown; do not infer absence. "
                        "Container observations remain usable.",
                    )
                )
        tools = DiagnosticTools(self.runtime, context, session.host, self.log_lines, self.log_bytes, group, inventory)
        if group:
            call = ToolCall("selected-group", "inspect_group", group.model_dump())
            messages.append(ModelMessage("assistant", "", (call,)))
            async for event in self._record_tool(call, tools, messages, deadline, 0, trace, strict=True):
                yield event
        async for event in self._explore(messages, tools, deadline, trace, int(group is not None)):
            yield event
        messages.append(ModelMessage("user", final_prompt(query)))
        async for event in self._finalize(messages, context, session.actor, deadline, trace):
            if event["type"] == "answer.ready":
                session.history.extend(
                    [
                        ModelMessage("user", self.redactor.text(query)),
                        ModelMessage("assistant", cast(str, event["answer"]["summary"])),
                    ]
                )
            yield event
        yield {"type": "turn.completed", "turn_id": trace.turn_id}

    async def _explore(
        self,
        messages: list[ModelMessage],
        tools: DiagnosticTools,
        deadline: float,
        trace: DiagnosticTrace,
        used: int = 0,
    ) -> AsyncGenerator[TurnEvent]:
        """Collect evidence within shared model, tool, and wall-clock budgets."""
        tool_calls = used
        for _ in range(self.max_model_calls - 2):
            yield trace.begin("model", "collect_evidence")
            reply = await _before_deadline(deadline, lambda: self.model.complete(messages, tool_specs()))
            yield trace.finish(reply=reply)
            messages.append(ModelMessage("assistant", reply.content, reply.tool_calls, native=reply.native))
            if not reply.tool_calls:
                break
            for call in reply.tool_calls:
                async for event in self._record_tool(call, tools, messages, deadline, tool_calls, trace):
                    yield event
                tool_calls += 1
            if tool_calls >= self.max_tool_calls:
                break

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
        messages.append(ModelMessage("tool", json.dumps(result), tool_call_id=call.id, tool_name=call.name))
        yield {"type": "tool.completed", "turn_id": trace.turn_id, "tool": name, "ok": "error" not in result}
        if strict and isinstance(result.get("error"), str):
            raise DockSightError(str(result["error"]), "Selected group could not be inspected", 502)

    async def _tool_result(self, call: ToolCall, tools: DiagnosticTools, deadline: float, used: int) -> JsonObject:
        """Return a safe tool result while preserving the absolute turn deadline."""
        try:
            if used >= self.max_tool_calls:
                raise DockSightError("tool_limit", "Tool budget exhausted", 409)
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
            reply = await _before_deadline(deadline, lambda: self.model.complete(messages, schema=proposal_schema()))
            yield trace.finish(reply=reply, preview=True)
            yield trace.begin("validation", "validate_diagnosis")
            try:
                if reply.tool_calls:
                    raise DockSightError("invalid_model_response", "Final response must not call tools", 502)
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
                        502,
                    ) from exc
                messages.extend(
                    [
                        ModelMessage("assistant", reply.content),
                        ModelMessage("user", _repair_feedback(exc, context, instruction)),
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
