import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from docksight.application.investigations.errors import StorageError
from docksight.application.ports.runtime import RuntimeMutationPort, RuntimeReadPort
from docksight.application.ports.state import ActionStore, AuditPort, StoredAction
from docksight.application.views.schemas import ActionView
from docksight.domain.actions import ActionState, Operation, PreparedAction, allowed_operations
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError, ErrorKind
from docksight.domain.runtime import ContainerSnapshot


def action_view(action: PreparedAction) -> ActionView:
    """Project an action's public state without its internal claim metadata."""
    return ActionView.model_validate(action, from_attributes=True)


class Actions:
    """Prepare scoped actions and durably protect each confirmed mutation claim."""

    def __init__(
        self,
        reader: RuntimeReadPort,
        writer: RuntimeMutationPort,
        store: ActionStore,
        audit: AuditPort,
        ttl: int = 300,
        timeout: float = 30,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Bind runtime ports, action storage, audit output, and execution limits."""
        self.reader = reader
        self.writer = writer
        self.store = store
        self.audit = audit
        self.ttl = ttl
        self.timeout = timeout
        self.clock = clock
        self._tasks: dict[str, asyncio.Task[ActionView]] = {}
        self._mutations: set[asyncio.Task[None]] = set()
        self._admissions: set[asyncio.Task[ActionView]] = set()
        self._accepting = True

    async def prepare(self, actor: str, host: str, container_id: str, operation: Operation) -> ActionView:
        """Capture a permitted operation against one exact container fingerprint."""
        self._require_admission()
        if not re.fullmatch(r"[a-f0-9]{64}", container_id):
            raise DockSightError("invalid_target", "Actions require an exact full container ID", ErrorKind.VALIDATION)
        snapshot = await self.reader.inspect(host, container_id)
        if snapshot.id != container_id or snapshot.host != host:
            raise DockSightError("target_changed", "Container identity changed", ErrorKind.CONFLICT)
        if operation not in allowed_operations(snapshot.state):
            raise DockSightError(
                "action_unavailable", "Operation is unavailable for this container state", ErrorKind.CONFLICT
            )
        action = PreparedAction(
            str(uuid4()),
            actor,
            host,
            container_id,
            operation,
            snapshot.fingerprint,
            self.clock() + timedelta(seconds=self.ttl),
        )
        stored = await self.store.add(action, self.clock())
        await self._mirror("action.prepared", stored.action)
        return action_view(stored.action)

    async def execute(self, action_id: str, actor: str, key: str, confirmed: bool) -> ActionView:
        """Claim once and shield execution from duplicate or disconnected callers."""
        self._require_admission()
        admission = asyncio.create_task(self._admit(action_id, actor, key, confirmed))
        self._admissions.add(admission)
        admission.add_done_callback(self._admission_finished)
        return await asyncio.shield(admission)

    def _require_admission(self) -> None:
        """Reject new mutation work after shutdown or a storage failure."""
        if not self._accepting:
            raise StorageError()

    def _admission_finished(self, task: asyncio.Task[ActionView]) -> None:
        """Release admission ownership and retrieve failures after observer cancellation."""
        self._admissions.discard(task)
        if not task.cancelled():
            task.exception()

    async def _admit(self, action_id: str, actor: str, key: str, confirmed: bool) -> ActionView:
        """Own the entire claim commit to execution-registration handoff through HTTP cancellation."""
        try:
            claim = await self.store.claim(action_id, actor, key, confirmed, self.clock())
            stored = claim.stored
            if claim.claimed:
                task = await self._register(stored)
            else:
                task = self._tasks.get(action_id)
                if task is None:
                    return action_view(stored.action)
            return await asyncio.shield(task)
        except StorageError:
            self._accepting = False
            raise

    async def _register(self, stored: StoredAction) -> asyncio.Task[ActionView]:
        """Register the claimed workflow or persist a failed-before-dispatch result."""
        workflow = self._run(stored)
        try:
            task = asyncio.create_task(workflow)
        except Exception:
            workflow.close()
            await self.store.complete(
                stored.action.id,
                stored.revision,
                ActionState.FAILED,
                "Action could not start before dispatch",
                self.clock(),
            )
            raise
        self._tasks[stored.action.id] = task
        task.add_done_callback(self._workflow_finished)
        return task

    def _workflow_finished(self, task: asyncio.Task[ActionView]) -> None:
        """Retrieve workflow failures and remove only the corresponding retained owner."""
        for action_id, current in tuple(self._tasks.items()):
            if current is task:
                del self._tasks[action_id]
        if not task.cancelled():
            task.exception()

    async def get(self, action_id: str, actor: str) -> ActionView:
        """Read the public action state within the requesting actor's scope."""
        return action_view((await self.store.get(action_id, actor, self.clock())).action)

    async def _run(self, stored: StoredAction) -> ActionView:
        """Revalidate, persist dispatch intent, execute once, and explicitly save the terminal result."""
        action = stored.action
        await self._mirror("action.claimed", action)
        try:
            async with asyncio.timeout(self.timeout):
                current = await self.reader.inspect(action.host, action.container_id)
                _validate_target(action, current)
                stored = await self.store.mark_dispatch(action.id, stored.revision, self.clock())
                task = self._start_mutation(action)
                await asyncio.shield(task)
            state, message = ActionState.SUCCEEDED, f"Container {action.operation} completed"
        except StorageError:
            self._accepting = False
            raise
        except (Exception, asyncio.CancelledError) as error:
            state, message = _failure(error, stored.phase == "dispatching")
        try:
            saved = await self.store.complete(action.id, stored.revision, state, message, self.clock())
        except StorageError:
            self._accepting = False
            raise
        await self._mirror(f"action.{state}", saved.action)
        return action_view(saved.action)

    def _start_mutation(self, action: PreparedAction) -> asyncio.Task[None]:
        """Track a mutation independently of caller cancellation and timeouts."""
        mutation = self.writer.restart if action.operation == "restart" else self.writer.stop
        task = asyncio.create_task(mutation(action.host, action.container_id))
        self._mutations.add(task)
        task.add_done_callback(self._mutation_finished)
        return task

    def _mutation_finished(self, job: asyncio.Task[None]) -> None:
        """Release finished mutation tasks and retrieve background exceptions."""
        self._mutations.discard(job)
        if not job.cancelled():
            job.exception()

    async def _mirror(self, event: str, action: PreparedAction) -> None:
        """Mirror a committed lifecycle event without making logging authoritative."""
        data: JsonObject = {
            "action_id": action.id,
            "actor": action.actor,
            "host": action.host,
            "container_id": action.container_id,
            "operation": action.operation,
            "state": action.state.value,
        }
        try:
            await self.audit.record(event, data)
        except Exception:
            return

    async def close(self) -> None:
        """Wait for action workflows and mutations before shutting down adapters."""
        self._accepting = False
        while self._admissions or self._tasks or self._mutations:
            pending: list[Awaitable[object]] = [*self._admissions, *self._tasks.values(), *self._mutations]
            await asyncio.shield(asyncio.gather(*pending, return_exceptions=True))


def _validate_target(action: PreparedAction, current: ContainerSnapshot) -> None:
    """Reject stale container identity, state, or prepared-action fingerprints."""
    if current.host != action.host or current.id != action.container_id or current.fingerprint != action.fingerprint:
        raise DockSightError("stale_action", "Container changed; prepare a new action", ErrorKind.CONFLICT)
    if action.operation not in allowed_operations(current.state):
        raise DockSightError("action_unavailable", "Operation is unavailable for this state", ErrorKind.CONFLICT)


def _failure(error: BaseException, dispatched: bool) -> tuple[ActionState, str]:
    """Treat every unsettled post-marker failure conservatively without retrying Docker."""
    if dispatched:
        return ActionState.INDETERMINATE, "Docker outcome is unknown; inspect the target before further changes"
    message = error.message if isinstance(error, DockSightError) else "Action failed before dispatch"
    return ActionState.FAILED, message
