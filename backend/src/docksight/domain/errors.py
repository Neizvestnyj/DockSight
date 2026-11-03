from enum import Enum


class ErrorKind(Enum):
    """Classify failures for callers without selecting a transport response."""

    INVALID = "invalid"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    VALIDATION = "validation"
    RATE_LIMIT = "rate_limit"
    CONFIGURATION = "configuration"
    DEPENDENCY = "dependency"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"


class DockSightError(Exception):
    """Carry a safe public code, message, and transport-independent failure category."""

    def __init__(self, code: str, message: str, kind: ErrorKind = ErrorKind.INVALID) -> None:
        """Keep public failure metadata separate from the underlying exception cause."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.kind = kind
