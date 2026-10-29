from dataclasses import dataclass
from typing import Final, Literal

type Language = Literal["en", "ru"]


@dataclass(frozen=True)
class Case:
    """Describe an actual Docker workload and the public diagnostic contract it exercises."""

    name: str
    services: tuple[str, ...]
    group: bool = False
    explicit: bool = False
    typo: bool = False

    def query(self, project: str, container_id: str, language: Language = "en") -> str:
        """Ask about the observed namespace or exact ID without suggesting a failure explanation."""
        if self.group:
            name = project[:-1] + "z" if self.typo else project
            return f"Что произошло в {name}?" if language == "ru" else f"What happened to {name}?"
        if language == "ru":
            return (
                f"Проверь контейнер {container_id}. Объясни, что случилось и что пока неизвестно. "
                "Покажи отдельные карточки container_status и log_anomalies."
            )
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
