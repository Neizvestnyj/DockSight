from typing import Final

from docker.models.containers import Container

FAILURES: Final = {
    "backend": (1, False, "DatabaseConnectionError"),
    "grafana": (1, False, "could not find Chat Id"),
    "oom": (137, True, "Starting a 256 MiB allocation"),
    "unknown": (137, False, "Worker ended without recording"),
    "database-stopped": (0, False, "database system is shut down"),
    "clean-shutdown": (0, False, "database system is shut down"),
}


def is_ready(name: str, row: Container) -> bool:
    """Check actual engine state and application readiness for each authored workload."""
    state = row.attrs["State"]
    if name in FAILURES:
        return state["Status"] == "exited"
    if name == "crash":
        return row.attrs["RestartCount"] >= 2
    if name in {"logs", "database", "database-current"}:
        return state["Status"] == "running" and row.exec_run(["test", "-f", "/tmp/ready"]).exit_code == 0
    return state.get("Health", {}).get("Status") == ("unhealthy" if name == "unhealthy" else "healthy")


def validate_failures(rows: dict[str, Container]) -> None:
    """Reject an unexpected failure on either side of a follow-up before testing the diagnosis."""
    for name, row in rows.items():
        if name not in FAILURES:
            continue
        exit_code, oom, marker = FAILURES[name]
        state = row.attrs["State"]
        output = row.logs(tail=100).decode("utf-8", errors="replace")
        if (state["ExitCode"], state["OOMKilled"]) != (exit_code, oom) or marker not in output:
            raise RuntimeError(f"Unexpected fixture failure for {name}; required workload was not reproduced")
