from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Case:
    """Describe an actual Docker workload and the public diagnostic contract it exercises."""

    name: str
    services: tuple[str, ...]
    group: bool = False
    explicit: bool = False
    typo: bool = False

    def query(self, project: str, container_id: str) -> str:
        """Ask about the observed namespace or exact ID without suggesting a failure explanation."""
        if self.group:
            name = project[:-1] + "z" if self.typo else project
            return f"What happened to {name}? Inspect the whole group and explain the failures."
        return (
            f"Investigate container {container_id}. Explain what happened and what remains unknown. "
            "Include separate container_status and log_anomalies cards."
        )


CASES: Final = (
    Case("compose-explicit", ("backend", "grafana", "nginx"), group=True, explicit=True),
    Case("compose-chat", ("backend", "grafana", "nginx"), group=True),
    Case("compose-typo", ("backend", "grafana", "nginx"), group=True, typo=True),
    Case("oom", ("oom",)),
    Case("crash-loop", ("crash",)),
    Case("truncated-logs", ("logs",)),
    Case("unknown-exit", ("unknown",)),
)
