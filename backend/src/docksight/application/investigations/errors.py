from docksight.application.investigations.contracts import ActorWorkspace, InvestigationWorkspace
from docksight.domain.errors import DockSightError, ErrorKind


class HistoryError(DockSightError):
    """Identify safe archive failures without reflecting persisted payloads."""


class StorageError(DockSightError):
    """Fail admission closed after a storage or process-ownership failure."""

    def __init__(self, code: str = "storage_unavailable", message: str = "Persistent storage is unavailable") -> None:
        """Expose a safe storage code while preserving private causes through exception chaining."""
        super().__init__(code, message, ErrorKind.UNAVAILABLE)


class WorkspaceConflict(HistoryError):
    """Return the current owned snapshot when an optimistic workspace update is stale."""

    def __init__(self, current: ActorWorkspace | InvestigationWorkspace) -> None:
        """Retain a detached safe workspace so callers can explicitly resolve the conflict."""
        super().__init__("workspace_conflict", "Workspace has changed", ErrorKind.CONFLICT)
        self.current = current


def not_found() -> HistoryError:
    """Keep foreign and missing archive identifiers indistinguishable."""
    return HistoryError("history_not_found", "Saved history was not found", ErrorKind.NOT_FOUND)


def capacity() -> HistoryError:
    """Reject additional work without removing saved history."""
    return HistoryError("history_capacity", "Saved history capacity has been reached", ErrorKind.CONFLICT)
