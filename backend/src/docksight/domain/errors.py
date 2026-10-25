class DockSightError(Exception):
    """Carry a safe public error code, message, and HTTP status across boundaries."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        """Keep transport-safe error metadata separate from the underlying cause."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
