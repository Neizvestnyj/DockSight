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
    spelling: Literal["exact", "spaced", "cyrillic", "ambiguous", "unscoped"] = "exact"

    @property
    def needs_selection(self) -> bool:
        """Require an observed scope choice for ambiguous names or bare incident questions."""
        return self.spelling in {"ambiguous", "unscoped"}

    def query(self, project: str, container_id: str, language: Language = "en") -> str:
        """Ask about the observed namespace or exact ID without suggesting a failure explanation."""
        if self.group:
            return self._group_query(project, language)
        if language == "ru":
            return (
                f"Проверь контейнер {container_id}. Объясни, что случилось и что пока неизвестно. "
                "Покажи отдельные карточки container_status и log_anomalies."
            )
        return (
            f"Investigate container {container_id}. Explain what happened and what remains unknown. "
            "Include separate container_status and log_anomalies cards."
        )

    def _group_query(self, project: str, language: Language) -> str:
        """Vary how a real group is named while keeping its diagnostic intent unchanged."""
        if self.spelling == "unscoped":
            return "Что случилось?" if language == "ru" else "What happened?"
        if self.spelling in {"cyrillic", "ambiguous"}:
            return (
                "Что не так \u0441 винтория инфра?"
                if language == "ru"
                else "What is wrong with винтория инфра? Please answer in English."
            )
        name = project[:-1] + "z" if self.typo else project
        if self.spelling == "spaced":
            name = name.replace("-", " ")
        return f"Что произошло в {name}?" if language == "ru" else f"What happened to {name}?"


FOLLOW_UP_CASE: Final = Case("compose-follow-up", ("backend", "grafana", "nginx"), group=True)
FOLLOW_UP_NOISY_CASE: Final = Case("compose-follow-up-noisy", ("backend", "grafana", "nginx"), group=True)
FOLLOW_UP_CASES: Final = (FOLLOW_UP_CASE, FOLLOW_UP_NOISY_CASE)

CASES: Final = (
    Case("compose-explicit", ("backend", "grafana", "nginx"), group=True, explicit=True),
    Case("compose-chat", ("backend", "grafana", "nginx"), group=True),
    Case("compose-typo", ("backend", "grafana", "nginx"), group=True, typo=True),
    Case("compose-spaced", ("backend", "grafana", "nginx"), group=True, spelling="spaced"),
    Case("compose-cyrillic", ("backend", "grafana", "nginx"), group=True, spelling="cyrillic"),
    Case("compose-ambiguous", ("backend", "grafana", "nginx"), group=True, spelling="ambiguous"),
    Case("compose-unscoped", ("backend", "grafana", "nginx"), group=True, spelling="unscoped"),
    Case("oom", ("oom",)),
    Case("crash-loop", ("crash",)),
    Case("truncated-logs", ("logs",)),
    Case("unknown-exit", ("unknown",)),
)
