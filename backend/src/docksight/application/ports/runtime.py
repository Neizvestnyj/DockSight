from typing import Literal, Protocol

from docksight.domain.runtime import (
    ContainerSnapshot,
    Host,
    LogBatch,
    ResourceMetrics,
    StackSummary,
)


class RuntimeReadPort(Protocol):
    """Expose sanitized runtime reads scoped to configured hosts."""

    def hosts(self) -> tuple[Host, ...]:
        """Return the configured public host inventory."""
        ...

    async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
        """Read bounded sanitized container snapshots for one host."""
        ...

    async def inspect(self, host: str, container_id: str) -> ContainerSnapshot:
        """Read one sanitized container snapshot on the selected host."""
        ...

    async def logs(self, host: str, container_id: str, lines: int, max_bytes: int) -> LogBatch:
        """Read sanitized container logs within explicit line and byte limits."""
        ...

    async def stats(self, host: str, container_id: str) -> ResourceMetrics:
        """Read current container metrics and retain missing values as unavailable."""
        ...

    async def stacks(self, host: str, kind: Literal["compose", "swarm"]) -> tuple[StackSummary, ...]:
        """Read Compose grouping or manager-only Swarm service summaries."""
        ...


class RuntimeMutationPort(Protocol):
    """Expose exact-container mutations separately from model-visible reads."""

    async def restart(self, host: str, container_id: str) -> None:
        """Restart the exact container selected by a validated action."""
        ...

    async def stop(self, host: str, container_id: str) -> None:
        """Stop the exact container selected by a validated action."""
        ...
