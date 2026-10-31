from dataclasses import dataclass
from datetime import datetime
from typing import Literal

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
type JsonObject = dict[str, JsonValue]


@dataclass(frozen=True)
class EvidenceRef:
    """Identify a timestamped, host-scoped runtime observation used by a diagnosis."""

    id: str
    kind: Literal["container", "logs", "stats", "stack", "env", "host"]
    host: str
    container_id: str | None
    observed_at: datetime
    data: JsonObject
    container_name: str | None = None
