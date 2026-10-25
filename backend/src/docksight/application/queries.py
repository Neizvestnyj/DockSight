from typing import Literal

from docksight.application.ports.runtime import RuntimeReadPort
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import (
    ContainerSnapshot,
    Host,
    LogBatch,
    ResourceMetrics,
    StackSummary,
)


class RuntimeQueries:
    def __init__(
        self, runtime: RuntimeReadPort, log_lines: int = 200, log_bytes: int = 65536
    ) -> None:
        self.runtime = runtime
        self.log_lines = log_lines
        self.log_bytes = log_bytes

    def hosts(self) -> tuple[Host, ...]:
        return self.runtime.hosts()

    def check_host(self, host: str) -> None:
        if host not in {item.id for item in self.runtime.hosts()}:
            raise DockSightError("host_not_found", "Configured host not found", 404)

    async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
        self.check_host(host)

        return await self.runtime.containers(host)

    async def inspect(self, host: str, container_id: str) -> ContainerSnapshot:
        self.check_host(host)

        return await self.runtime.inspect(host, container_id)

    async def logs(self, host: str, container_id: str, lines: int) -> LogBatch:
        snapshot = await self.inspect(host, container_id)
        if not 1 <= lines <= self.log_lines:
            raise DockSightError(
                "invalid_log_limit", "Requested log limit exceeds configured bounds", 422
            )

        return await self.runtime.logs(host, snapshot.id, lines, self.log_bytes)

    async def stats(self, host: str, container_id: str) -> ResourceMetrics:
        snapshot = await self.inspect(host, container_id)

        return await self.runtime.stats(host, snapshot.id)

    async def stacks(
        self, host: str, kind: Literal["compose", "swarm"]
    ) -> tuple[StackSummary, ...]:
        self.check_host(host)

        return await self.runtime.stacks(host, kind)
