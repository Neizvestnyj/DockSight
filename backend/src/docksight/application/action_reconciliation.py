from collections.abc import Callable, Collection
from datetime import UTC, datetime

from docksight.application.ports.runtime import RuntimeReadPort
from docksight.application.ports.state import ActionStore, BlockedTarget, ReconcileTarget, ReconciliationObservation
from docksight.domain.errors import DockSightError, ErrorKind


def validate_reconciliation(
    current: BlockedTarget, command: ReconcileTarget, observation: ReconciliationObservation
) -> None:
    """Reject incomplete confirmations and stale guards before any reconciliation writes."""
    if not command.acknowledge_unknown_outcome or not command.reason.strip() or not command.operator.strip():
        raise DockSightError("reconciliation_confirmation", "Explicit unknown-outcome acknowledgement is required")
    if command.confirm_target != f"{current.host}/{current.container_id}":
        raise DockSightError("reconciliation_target", "Exact target confirmation does not match", ErrorKind.CONFLICT)
    if not current.blocked or command.expected_revision != current.revision:
        raise DockSightError("reconciliation_conflict", "Target guard changed; inspect it again", ErrorKind.CONFLICT)
    if (observation.host, observation.container_id) != (current.host, current.container_id):
        raise DockSightError("reconciliation_target", "Docker observation target differs", ErrorKind.CONFLICT)


class ActionReconciliation:
    """Observe configured Docker targets and explicitly reconcile offline operator confirmations."""

    def __init__(
        self,
        reader: RuntimeReadPort,
        store: ActionStore,
        actors: Collection[str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Bind configured host reads and actor labels without acquiring runtime mutation authority."""
        self.reader = reader
        self.store = store
        self.actors = frozenset(actors)
        self.clock = clock

    async def inspect(self, action_id: str) -> BlockedTarget:
        """Preview the current guard alongside a fresh exact-target Docker observation."""
        current = await self.store.inspect_block(action_id)
        observation = await self._observe(current)
        return current.model_copy(update={"observation": observation})

    async def reconcile(self, command: ReconcileTarget) -> BlockedTarget:
        """Reread Docker and atomically apply a confirmed guard revision without resending a mutation."""
        if command.actor not in self.actors:
            raise DockSightError("actor_unknown", "Reconciliation actor is not configured", ErrorKind.VALIDATION)
        current = await self.store.inspect_block(command.action_id)
        observation = await self._observe(current)
        validate_reconciliation(current, command, observation)
        return await self.store.reconcile(command, observation, self.clock())

    async def _observe(self, current: BlockedTarget) -> ReconciliationObservation:
        """Accept verified removal while preserving blocks on unavailable or mismatched Docker reads."""
        if current.host not in {host.id for host in self.reader.hosts()}:
            raise DockSightError("host_not_found", "Reconciliation host is not configured", ErrorKind.NOT_FOUND)
        try:
            snapshot = await self.reader.inspect(current.host, current.container_id)
        except DockSightError as error:
            if error.code != "container_not_found":
                raise
            return ReconciliationObservation(
                host=current.host, container_id=current.container_id, observed_at=self.clock(), exists=False
            )
        if (snapshot.host, snapshot.id) != (current.host, current.container_id):
            raise DockSightError("target_changed", "Docker observation identity changed", ErrorKind.CONFLICT)
        return ReconciliationObservation(
            host=snapshot.host,
            container_id=snapshot.id,
            observed_at=self.clock(),
            exists=True,
            fingerprint=snapshot.fingerprint,
            state=snapshot.state,
        )
