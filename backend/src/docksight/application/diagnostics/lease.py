from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from docksight.application.events import TurnEvent
from docksight.application.investigations.contracts import DiagnosticCommand

if TYPE_CHECKING:
    from docksight.application.diagnostics.use_case import Diagnostics


class DiagnosticLease:
    """Own one diagnostic semaphore slot until its retained workflow has completely settled."""

    def __init__(self, diagnostics: Diagnostics, deadline: float) -> None:
        """Bind the selected model and monotonic deadline without acquiring another slot."""
        self.diagnostics, self.deadline = diagnostics, deadline
        self._closed = self._used = False

    async def run(self, command: DiagnosticCommand) -> AsyncGenerator[TurnEvent]:
        """Execute exactly once with preallocated IDs and the already-held capacity reservation."""
        if self._closed or self._used:
            raise RuntimeError("Diagnostic reservation was already consumed")
        self._used = True
        stream = self.diagnostics.run_reserved(command, self.deadline)
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()

    async def close(self) -> None:
        """Release shared capacity idempotently after the owner has closed its diagnostic stream."""
        if not self._closed:
            self._closed = True
            self.diagnostics.release()
