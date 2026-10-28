import json
import time
from datetime import UTC, datetime
from typing import Final, Literal, cast

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from docksight.application.events import TraceStepEvent
from docksight.application.ports.models import ModelReply
from docksight.application.redaction import Redactor
from docksight.application.views.schemas import DiagnosisProposal, WidgetProposal
from docksight.domain.diagnostics import JsonObject, JsonValue

_PREVIEW_BYTES: Final = 16384
_PREVIEW_INPUT_BYTES: Final = 65536


class TraceIssue(BaseModel):
    """Expose validation codes and known field paths without submitted names or values."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    type: str = Field(max_length=64)
    loc: list[str | int] = Field(max_length=8)


class TraceStep(BaseModel):
    """Describe one measured application operation without prompts or provider-native data."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(max_length=16)
    kind: Literal["model", "tool", "validation"]
    operation: str = Field(max_length=128)
    state: Literal["running", "succeeded", "failed"] = "running"
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    code: str | None = Field(default=None, max_length=64)
    issues: list[TraceIssue] = Field(default_factory=list[TraceIssue], max_length=8)
    response: str | None = Field(default=None, max_length=_PREVIEW_BYTES)
    response_truncated: bool = False


def schema_issues(error: ValidationError) -> list[TraceIssue]:
    """Keep bounded error codes and schema paths without reflecting arbitrary model fields."""
    fields = DiagnosisProposal.model_fields.keys() | WidgetProposal.model_fields.keys()
    return [
        TraceIssue(
            type=issue["type"][:64],
            loc=[part if isinstance(part, int) or part in fields else "<extra_field>" for part in issue["loc"][:8]],
        )
        for issue in error.errors(include_url=False, include_input=False, include_context=False)[:8]
    ]


def _redact_values(value: JsonValue, redactor: Redactor) -> JsonValue:
    """Redact string values before JSON escaping can obscure exact configured secrets."""
    if isinstance(value, str):
        return redactor.text(value)
    if isinstance(value, list):
        return [_redact_values(item, redactor) for item in value]
    if isinstance(value, dict):
        return {key: _redact_values(item, redactor) for key, item in value.items()}
    return value


def _proposal_preview(reply: ModelReply, redactor: Redactor) -> tuple[str | None, bool]:
    """Preview only recognized final proposal fields, withholding invalid or oversized input."""
    if reply.tool_calls or len(reply.content.encode("utf-8")) > _PREVIEW_INPUT_BYTES:
        return None, len(reply.content.encode("utf-8")) > _PREVIEW_INPUT_BYTES
    try:
        proposal = DiagnosisProposal.model_validate_json(reply.content)
    except ValidationError:
        return None, False
    public = _redact_values(cast(JsonObject, proposal.model_dump(mode="json")), redactor)
    encoded = json.dumps(public, ensure_ascii=False, indent=2).encode("utf-8")
    return encoded[:_PREVIEW_BYTES].decode("utf-8", errors="ignore"), len(encoded) > _PREVIEW_BYTES


class DiagnosticTrace:
    """Measure sequential diagnostic steps and produce immutable public event snapshots."""

    def __init__(self, turn_id: str, redactor: Redactor) -> None:
        """Keep one active operation; completed events belong only to the current SSE stream."""
        self.turn_id = turn_id
        self.redactor = redactor
        self.sequence = 0
        self.active: TraceStep | None = None
        self.started = 0.0

    def begin(self, kind: Literal["model", "tool", "validation"], operation: str) -> TraceStepEvent:
        """Announce an operation before awaiting its external or validation work."""
        self.sequence += 1
        self.active = TraceStep(
            id=f"step-{self.sequence}", kind=kind, operation=operation, started_at=datetime.now(UTC)
        )
        self.started = time.monotonic()
        return self._event(self.active)

    def finish(
        self,
        *,
        code: str | None = None,
        reply: ModelReply | None = None,
        preview: bool = False,
        issues: list[TraceIssue] | None = None,
    ) -> TraceStepEvent:
        """Finish the active step with measured duration and optional sanitized final output."""
        if self.active is None:
            raise RuntimeError("A trace step must start before it finishes")
        response, clipped = _proposal_preview(reply, self.redactor) if preview and reply else (None, False)
        completed = self.active.model_copy(
            update={
                "state": "failed" if code else "succeeded",
                "finished_at": datetime.now(UTC),
                "duration_ms": max(0, round((time.monotonic() - self.started) * 1000)),
                "code": code,
                "issues": issues or [],
                "input_tokens": reply.input_tokens if reply else None,
                "output_tokens": reply.output_tokens if reply else None,
                "response": response,
                "response_truncated": clipped,
            }
        )
        self.active = None
        return self._event(completed)

    def _event(self, step: TraceStep) -> TraceStepEvent:
        """Serialize the owned DTO rather than exposing mutable recorder state."""
        return {"type": "trace.step", "turn_id": self.turn_id, "step": cast(JsonObject, step.model_dump(mode="json"))}
