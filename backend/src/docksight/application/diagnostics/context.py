import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Literal

from docksight.application.views.schemas import GroupInspection, HostInspection, TargetSelection
from docksight.domain.diagnostics import EvidenceRef, JsonObject
from docksight.domain.errors import DockSightError, ErrorKind
from docksight.domain.runtime import ContainerSnapshot, LogBatch, StackSummary

EVIDENCE_BYTES: Final = 65536


@dataclass
class EvidenceContext:
    """Own a turn's bounded evidence and typed runtime snapshots."""

    evidence: dict[str, EvidenceRef] = field(default_factory=dict[str, EvidenceRef])
    snapshots: dict[str, ContainerSnapshot] = field(default_factory=dict[str, ContainerSnapshot])
    logs: dict[str, LogBatch] = field(default_factory=dict[str, LogBatch])
    stacks: dict[str, tuple[StackSummary, ...]] = field(default_factory=dict[str, tuple[StackSummary, ...]])
    used_bytes: int = 0
    group: GroupInspection | None = None
    selection: TargetSelection | None = None
    container_id: str | None = None
    host_overview: HostInspection | None = None

    @property
    def remaining_bytes(self) -> int:
        """Report remaining serialized data capacity for this turn."""
        return EVIDENCE_BYTES - self.used_bytes

    def record(
        self,
        kind: Literal["container", "logs", "stats", "stack", "env", "host"],
        host: str,
        data: JsonObject,
        snapshot: ContainerSnapshot | None = None,
        logs: LogBatch | None = None,
        stacks: tuple[StackSummary, ...] | None = None,
    ) -> EvidenceRef:
        """Assign an evidence ID and retain its typed data within turn limits."""
        size = len(json.dumps(data, ensure_ascii=False).encode())
        if len(self.evidence) >= 64 or size > self.remaining_bytes:
            raise DockSightError(
                "evidence_limit", "Evidence budget reached; finalize with collected evidence", ErrorKind.CONFLICT
            )
        evidence_id = f"e{len(self.evidence) + 1}"
        item = EvidenceRef(
            evidence_id,
            kind,
            host,
            snapshot.id if snapshot else None,
            datetime.now(UTC),
            data,
            container_name=snapshot.name if snapshot else None,
        )
        self.evidence[evidence_id] = item
        self.used_bytes += size
        if snapshot is not None:
            self.snapshots[evidence_id] = snapshot
        if logs is not None:
            self.logs[evidence_id] = logs
        if stacks is not None:
            self.stacks[evidence_id] = stacks

        return item
