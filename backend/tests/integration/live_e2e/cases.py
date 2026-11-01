from dataclasses import dataclass
from typing import Final, Literal

from tests.integration.live_e2e.causal_checks import CausalProfile

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
    peer_service: Literal["backend", "database", "database-stopped", "clean-shutdown"] = "backend"
    causal_profile: CausalProfile | None = None
    production_limits: bool = False

    @property
    def log_limits(self) -> tuple[int, int]:
        """Use deployed budgets for representative cases and smaller budgets for intentional tail truncation."""
        return (200, 65536) if self.production_limits or self.spelling == "unscoped" else (30, 2048)

    @property
    def needs_selection(self) -> bool:
        """Require an observed scope choice only for an explicitly ambiguous resource name."""
        return self.spelling == "ambiguous"

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
        if self.name == "compose-healthy":
            return {
                "ru": f"Покажи текущее состояние контейнера в Compose-проекте {project}.",
                "en": f"Show the current state of the container in Compose project {project}.",
            }[language]
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
FOLLOW_UP_NOISY_CASE: Final = Case(
    "compose-follow-up-noisy",
    ("backend", "grafana", "nginx"),
    group=True,
    peer_service="database",
    causal_profile="running_history",
)
FOLLOW_UP_SHUTDOWN_CASE: Final = Case(
    "compose-follow-up-shutdown",
    ("backend", "grafana", "nginx"),
    group=True,
    peer_service="clean-shutdown",
    causal_profile="clean_shutdown",
    production_limits=True,
)
FOLLOW_UP_CASES: Final = (FOLLOW_UP_CASE, FOLLOW_UP_NOISY_CASE, FOLLOW_UP_SHUTDOWN_CASE)

CASES: Final = (
    Case("compose-healthy", ("nginx",), group=True, production_limits=True),
    Case("compose-explicit", ("backend", "grafana", "nginx"), group=True, explicit=True),
    Case("compose-chat", ("backend", "grafana", "nginx"), group=True),
    Case("compose-typo", ("backend", "grafana", "nginx"), group=True, typo=True),
    Case("compose-spaced", ("backend", "grafana", "nginx"), group=True, spelling="spaced"),
    Case("compose-cyrillic", ("backend", "grafana", "nginx"), group=True, spelling="cyrillic"),
    Case("compose-ambiguous", ("backend", "grafana", "nginx"), group=True, spelling="ambiguous"),
    Case("compose-unscoped", ("backend", "grafana", "nginx", "database-stopped"), group=True, spelling="unscoped"),
    Case("oom", ("oom",), causal_profile="oom", production_limits=True),
    Case("crash-loop", ("crash",)),
    Case("truncated-logs", ("logs",)),
    Case("unknown-exit", ("unknown",), causal_profile="unknown_exit", production_limits=True),
    Case("clean-shutdown", ("clean-shutdown",), causal_profile="clean_shutdown", production_limits=True),
    Case("unhealthy", ("unhealthy",), causal_profile="running_unhealthy", production_limits=True),
    Case("running-history", ("database-current",), causal_profile="running_history", production_limits=True),
)

SUITES: Final = {
    "causal": (
        "oom",
        "unknown-exit",
        "clean-shutdown",
        "unhealthy",
        "running-history",
        "compose-follow-up-noisy",
        "compose-follow-up-shutdown",
    ),
}


def selected_scenarios(names: list[str] | None, suites: list[str] | None) -> list[str] | None:
    """Combine explicit scenarios with named packages without duplicating model calls or changing default selection."""
    if not names and not suites:
        return None
    return list(dict.fromkeys([*(names or []), *(name for suite in suites or [] for name in SUITES[suite])]))
