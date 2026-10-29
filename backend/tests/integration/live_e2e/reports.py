import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tests.integration.live_e2e.cases import Case
from tests.integration.live_e2e.lab import ComposeLab


def report_path(artifacts: Path, model: str, case: Case, language: str, path: str = "http") -> Path:
    """Give each model, locale, flow, and transport an independent filesystem-safe artifact name."""
    slug = re.sub(r"[^a-z0-9]+", "-", model.lower())[:64]
    digest = hashlib.sha256(model.encode()).hexdigest()[:8]
    return artifacts / f"{slug}-{digest}-{case.name}-{language}-{path}.json"


def record_run(
    target: Path, lab: ComposeLab, model: str, started: str, payload: dict[str, Any], events: list[dict[str, Any]]
) -> None:
    """Retain successful and failed public responses without credentials or raw inspect documents."""
    target.write_text(
        json.dumps(
            {
                "model": model,
                "case": lab.case.name,
                "started_at": started,
                "input": payload,
                "fixture": lab.facts(),
                "events": events,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
