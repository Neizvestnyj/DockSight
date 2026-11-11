from typing import Final

from docksight.application.diagnostics.tools import tool_specs
from docksight.application.diagnostics.trace import TraceStep
from docksight.application.events import TurnEvent
from docksight.application.investigations.contracts import SavedTurn, TurnError, TurnOutcome, TurnProgress, TurnUpdate
from docksight.application.investigations.errors import capacity
from docksight.application.redaction import Redactor
from docksight.application.views.schemas import DiagnosisResponse, TargetSelection

_TOOLS: Final = frozenset({"resolve_target", *(tool.name for tool in tool_specs())})
_OPERATIONS: Final = _TOOLS | {
    "collect_evidence",
    "final_response",
    "repair_response",
    "validate_diagnosis",
    "unapproved_tool",
}


class TurnObservations:
    """Normalize transient diagnostics into bounded safe persisted observations and one buffered result."""

    def __init__(self, redactor: Redactor) -> None:
        """Keep result payloads private until the terminal transaction succeeds."""
        self.redactor = redactor
        self.answer: DiagnosisResponse | None = None
        self.selection: TargetSelection | None = None
        self.error: TurnError | None = None

    def consume(self, event: TurnEvent, saved: SavedTurn) -> TurnUpdate | None:
        """Strip model previews and retain only validated card, progress, and trace values."""
        if event["type"] == "answer.ready":
            self.answer = DiagnosisResponse.model_validate(event["answer"])
        elif event["type"] == "clarification.required":
            self.selection = TargetSelection.model_validate(event["selection"])
        elif event["type"] == "turn.failed":
            self.error = TurnError(
                code=self.redactor.text(event["code"])[:64], message=self.redactor.text(event["message"])[:512]
            )
        elif event["type"] == "trace.step":
            return self._trace(event["step"], saved)
        elif event["type"] in {"tool.started", "tool.completed"}:
            return self._progress(event, saved)
        return None

    def _trace(self, value: object, saved: SavedTurn) -> TurnUpdate:
        """Remove transient response previews before constructing a persisted trace step."""
        step = TraceStep.model_validate(value).model_copy(update={"response": None, "response_truncated": False})
        step = step.model_copy(
            update={
                "operation": step.operation if step.operation in _OPERATIONS else "unapproved_operation",
                "code": self.redactor.text(step.code)[:64] if step.code else None,
            }
        )
        steps = [item for item in saved.trace if item.id != step.id]
        steps.append(step)
        if len(steps) > 133:
            raise capacity()
        return TurnUpdate(
            expected_revision=saved.revision,
            progress=saved.progress,
            progress_truncated=saved.progress_truncated,
            trace=tuple(steps),
        )

    def _progress(self, event: TurnEvent, saved: SavedTurn) -> TurnUpdate:
        """Coalesce completion with its latest running tool and explicitly mark bounded overflow."""
        progress, truncated = list(saved.progress), saved.progress_truncated
        if event["type"] == "tool.started":
            if len(progress) == 100:
                truncated = True
            else:
                progress.append(TurnProgress(tool=self._tool_name(event["tool"]), state="running"))
        elif event["type"] == "tool.completed":
            self._complete_progress(progress, self._tool_name(event["tool"]), event["ok"])
        return TurnUpdate(
            expected_revision=saved.revision, progress=tuple(progress), progress_truncated=truncated, trace=saved.trace
        )

    def _complete_progress(self, progress: list[TurnProgress], tool: str, ok: bool) -> None:
        """Replace the latest matching start without treating omitted overflow as another tool's completion."""
        matching = [index for index, row in enumerate(progress) if row.tool == tool and row.state == "running"]
        if matching:
            progress[matching[-1]] = TurnProgress(tool=tool, state="succeeded" if ok else "failed")

    def _tool_name(self, name: str) -> str:
        """Keep approved operation names instead of persisting arbitrary model-selected call text."""
        return name if name in _TOOLS else "unapproved_tool"

    def outcome(self, revision: int) -> TurnOutcome:
        """Require a final validated answer, clarification, or public error before success."""
        if self.error is not None:
            return TurnOutcome(expected_revision=revision, state="failed", error=self.error)
        if self.selection is not None:
            return TurnOutcome(expected_revision=revision, state="awaiting_selection", selection=self.selection)
        if self.answer is not None:
            return TurnOutcome(expected_revision=revision, state="completed", answer=self.answer)
        return TurnOutcome(
            expected_revision=revision,
            state="failed",
            error=TurnError(code="turn_failed", message="Diagnostic did not produce a validated result"),
        )
