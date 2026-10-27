import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import cast
from uuid import uuid4

from pydantic import ValidationError

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.diagnostics.prompts import FINAL_PROMPT, SYSTEM_PROMPT
from docksight.application.diagnostics.tools import DiagnosticTools, tool_specs
from docksight.application.events import TurnEvent
from docksight.application.ports.models import ModelMessage, ModelPort, ToolCall
from docksight.application.ports.runtime import RuntimeReadPort
from docksight.application.ports.state import SessionStore
from docksight.application.redaction import Redactor
from docksight.application.views.assembler import ViewAssembler
from docksight.application.views.registry import proposal_schema
from docksight.application.views.schemas import DiagnosisProposal, DiagnosisResponse, WidgetProposal
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError


async def _before_deadline[T](deadline: float, operation: Callable[[], Awaitable[T]]) -> T:
    """Keep the deadline across yields without keeping a task-bound timeout scope."""
    if asyncio.get_running_loop().time() >= deadline:
        raise TimeoutError
    async with asyncio.timeout_at(deadline):
        return await operation()


def _schema_issues(error: ValidationError) -> list[dict[str, object]]:
    """Keep bounded error codes and known schema paths without submitted names or values."""
    fields = DiagnosisProposal.model_fields.keys() | WidgetProposal.model_fields.keys()
    return [
        {
            "type": issue["type"],
            "loc": [part if isinstance(part, int) or part in fields else "<extra_field>" for part in issue["loc"]],
        }
        for issue in error.errors(include_url=False, include_input=False, include_context=False)[:8]
    ]


def _repair_feedback(error: ValidationError | DockSightError, context: EvidenceContext) -> str:
    """Explain validation failures with field locations and trusted evidence groups, without raw values."""
    failure: dict[str, object]
    if isinstance(error, ValidationError):
        failure = {"code": "invalid_schema", "issues": _schema_issues(error)}
    else:
        failure = {"code": error.code, "message": error.message}
    groups: dict[tuple[str, str], list[str]] = {}
    for ref, snapshot in context.snapshots.items():
        groups.setdefault((snapshot.host, snapshot.id), []).append(ref)
    return json.dumps(
        {
            "instruction": FINAL_PROMPT
            + "\nCorrect the reported error. Each container evidence group is one container.",
            "error": failure,
            "evidence_ids": list(context.evidence),
            "container_evidence_groups": list(groups.values()),
            "log_evidence_ids": list(context.logs),
            "stack_evidence_ids": list(context.stacks),
        }
    )


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

    async def stream(
        self, actor: str, host: str, query: str, session_id: str | None = None
    ) -> AsyncGenerator[TurnEvent]:
        """Lease a scoped session and emit one terminal event for a bounded turn."""
        turn_id = str(uuid4())
        deadline = asyncio.get_running_loop().time() + self.timeout
        try:
            if host not in {item.id for item in self.runtime.hosts()}:
                raise DockSightError("host_not_found", "Configured host not found", 404)
            if not query.strip() or len(query) > 4000:
                raise DockSightError("invalid_query", "Query must contain 1-4000 characters", 422)
            if self._slots.locked():
                raise DockSightError("turn_capacity", "Diagnostic capacity reached; retry later", 503)
            async with (
                self._slots,
                self.sessions.lease(session_id, actor, host) as session,
            ):
                yield {"type": "turn.started", "turn_id": turn_id, "session_id": session.id}
                messages = [
                    ModelMessage("system", SYSTEM_PROMPT),
                    *session.history,
                    ModelMessage("user", self.redactor.text(query)),
                ]
                context = EvidenceContext()
                tools = DiagnosticTools(self.runtime, context, host, self.log_lines, self.log_bytes)
                async for event in self._explore(messages, tools, turn_id, deadline):
                    yield event
                messages.append(ModelMessage("user", FINAL_PROMPT))
                answer = await _before_deadline(
                    deadline,
                    lambda: self._finalize(messages, context, actor),
                )
                session.history.extend(
                    [
                        ModelMessage("user", self.redactor.text(query)),
                        ModelMessage("assistant", answer.summary),
                    ]
                )
                yield {
                    "type": "answer.ready",
                    "turn_id": turn_id,
                    "answer": cast(JsonObject, answer.model_dump(mode="json")),
                }
                yield {"type": "turn.completed", "turn_id": turn_id}
        except TimeoutError:
            yield {
                "type": "turn.failed",
                "turn_id": turn_id,
                "code": "turn_timeout",
                "message": "Diagnostic turn timed out",
            }
        except DockSightError as exc:
            yield {
                "type": "turn.failed",
                "turn_id": turn_id,
                "code": exc.code,
                "message": exc.message,
            }

    async def _explore(
        self, messages: list[ModelMessage], tools: DiagnosticTools, turn_id: str, deadline: float
    ) -> AsyncGenerator[TurnEvent]:
        """Collect evidence within shared model, tool, and wall-clock budgets."""
        tool_calls = 0
        for _ in range(self.max_model_calls - 2):
            reply = await _before_deadline(deadline, lambda: self.model.complete(messages, tool_specs()))
            messages.append(ModelMessage("assistant", reply.content, reply.tool_calls, native=reply.native))
            if not reply.tool_calls:
                break
            for call in reply.tool_calls:
                name = self.redactor.text(call.name)
                yield {"type": "tool.started", "turn_id": turn_id, "tool": name}
                result = await self._tool_result(call, tools, deadline, tool_calls)
                tool_calls += 1
                messages.append(ModelMessage("tool", json.dumps(result), tool_call_id=call.id, tool_name=call.name))
                yield {
                    "type": "tool.completed",
                    "turn_id": turn_id,
                    "tool": name,
                    "ok": "error" not in result,
                }
            if tool_calls >= self.max_tool_calls:
                break

    async def _tool_result(self, call: ToolCall, tools: DiagnosticTools, deadline: float, used: int) -> JsonObject:
        """Return a safe tool result while preserving the absolute turn deadline."""
        try:
            if used >= self.max_tool_calls:
                raise DockSightError("tool_limit", "Tool budget exhausted", 409)
            return await _before_deadline(deadline, lambda: tools.execute(call))
        except DockSightError as exc:
            return {"error": exc.code, "message": exc.message}

    async def _finalize(self, messages: list[ModelMessage], context: EvidenceContext, actor: str) -> DiagnosisResponse:
        """Validate the final proposal and allow one budgeted schema or evidence repair."""
        for attempt in range(2):
            reply = await self.model.complete(messages, schema=proposal_schema())
            try:
                if reply.tool_calls:
                    raise DockSightError("invalid_model_response", "Final response must not call tools", 502)
                proposal = DiagnosisProposal.model_validate_json(reply.content)
                proposal.summary = self.redactor.text(proposal.summary)

                return await self.assembler.build(proposal, context, actor)
            except (ValidationError, DockSightError) as exc:
                if attempt:
                    raise DockSightError(
                        "invalid_diagnosis",
                        "Model could not produce a valid evidence-backed diagnosis",
                        502,
                    ) from exc
                messages.extend(
                    [
                        ModelMessage("assistant", reply.content),
                        ModelMessage("user", _repair_feedback(exc, context)),
                    ]
                )
        raise AssertionError("Unreachable finalization state")
