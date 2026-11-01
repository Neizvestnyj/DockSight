from typing import Literal

from docksight.application.ports.runtime import RuntimeReadPort
from docksight.domain.errors import DockSightError, ErrorKind
from docksight.domain.runtime import (
    ContainerSnapshot,
    Host,
    LogBatch,
    ResourceMetrics,
    StackSummary,
)


class RuntimeQueries:
    """Validate host scope and expose bounded runtime reads to inbound adapters."""

    def __init__(self, runtime: RuntimeReadPort, log_lines: int = 200, log_bytes: int = 65536) -> None:
        """Bind the read port and configured log response limits."""
        self.runtime = runtime
        self.log_lines = log_lines
        self.log_bytes = log_bytes

    def hosts(self) -> tuple[Host, ...]:
        """Return the configured public host inventory."""
        return self.runtime.hosts()

    def check_host(self, host: str) -> None:
        """Reject host identifiers outside the operator-configured inventory."""
        if host not in {item.id for item in self.runtime.hosts()}:
            raise DockSightError("host_not_found", "Configured host not found", ErrorKind.NOT_FOUND)

    async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
        """Read bounded sanitized container snapshots for one host."""
        self.check_host(host)

        return await self.runtime.containers(host)

    async def inspect(self, host: str, container_id: str) -> ContainerSnapshot:
        """Read one sanitized container snapshot on the selected host."""
        self.check_host(host)

        return await self.runtime.inspect(host, container_id)

    async def logs(self, host: str, container_id: str, lines: int) -> LogBatch:
        """Read sanitized container logs within explicit line and byte limits."""
        snapshot = await self.inspect(host, container_id)
        if not 1 <= lines <= self.log_lines:
            raise DockSightError(
                "invalid_log_limit", "Requested log limit exceeds configured bounds", ErrorKind.VALIDATION
            )

        return await self.runtime.logs(host, snapshot.id, lines, self.log_bytes)

    async def stats(self, host: str, container_id: str) -> ResourceMetrics:
        """Read current container metrics and retain missing values as unavailable."""
        snapshot = await self.inspect(host, container_id)

        return await self.runtime.stats(host, snapshot.id)

    async def stacks(self, host: str, kind: Literal["compose", "swarm"]) -> tuple[StackSummary, ...]:
        """Read Compose grouping or manager-only Swarm service summaries."""
        self.check_host(host)

        return await self.runtime.stacks(host, kind)
