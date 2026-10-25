import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from docksight.application.ports.runtime import RuntimeMutationPort, RuntimeReadPort
from docksight.application.ports.state import ActionStore, AuditPort
from docksight.application.views.schemas import ActionView
from docksight.domain.actions import ActionState, Operation, PreparedAction, allowed_operations
from docksight.domain.diagnostics import JsonObject
from docksight.domain.errors import DockSightError


def action_view(action: PreparedAction) -> ActionView:
    return ActionView.model_validate(action, from_attributes=True)


class Actions:
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
        self.reader = reader
        self.writer = writer
        self.store = store
        self.audit = audit
        self.ttl = ttl
        self.timeout = timeout
        self.clock = clock
        self._tasks: dict[str, asyncio.Task[ActionView]] = {}
        self._mutations: set[asyncio.Task[None]] = set()

    async def prepare(
        self, actor: str, host: str, container_id: str, operation: Operation
    ) -> ActionView:
        if not re.fullmatch(r"[a-f0-9]{64}", container_id):
            raise DockSightError(
                "invalid_target", "Actions require an exact full container ID", 422
            )
        snapshot = await self.reader.inspect(host, container_id)
        if snapshot.id != container_id or snapshot.host != host:
            raise DockSightError("target_changed", "Container identity changed", 409)
        if operation not in allowed_operations(snapshot.state):
            raise DockSightError(
                "action_unavailable", "Operation is unavailable for this container state", 409
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
        await self.store.add(action)

        return action_view(action)

    async def execute(self, action_id: str, actor: str, key: str, confirmed: bool) -> ActionView:
        action, claimed = await self.store.claim(action_id, actor, key, confirmed, self.clock())
        if claimed:
            task = asyncio.create_task(self._run(action))
            self._tasks[action.id] = task
            task.add_done_callback(lambda _: self._tasks.pop(action.id, None))
        else:
            task = self._tasks.get(action.id)
            if task is None:
                return action_view(action)

        return await asyncio.shield(task)

    async def get(self, action_id: str, actor: str) -> ActionView:
        return action_view(await self.store.get(action_id, actor))

    async def _run(self, action: PreparedAction) -> ActionView:
        data: JsonObject = {
            "action_id": action.id,
            "actor": action.actor,
            "host": action.host,
            "container_id": action.container_id,
            "operation": action.operation,
        }
        try:
            await self.audit.record("action.started", data)
        except Exception:
            action.finish(ActionState.FAILED, "Audit output unavailable; action was not executed")

            return action_view(action)
        started = False
        try:
            async with (
                asyncio.timeout(self.timeout),
                self.store.target_lock(action.host, action.container_id),
            ):
                current = await self.reader.inspect(action.host, action.container_id)
                if current.id != action.container_id or current.fingerprint != action.fingerprint:
                    raise DockSightError(
                        "stale_action", "Container changed; prepare a new action", 409
                    )
                if action.operation not in allowed_operations(current.state):
                    raise DockSightError(
                        "action_unavailable", "Operation is unavailable for this state", 409
                    )
                mutation = (
                    self.writer.restart if action.operation == "restart" else self.writer.stop
                )
                task = asyncio.create_task(mutation(action.host, action.container_id))
                self._mutations.add(task)

                def finished(job: asyncio.Task[None]) -> None:
                    self._mutations.discard(job)
                    if not job.cancelled():
                        job.exception()

                task.add_done_callback(finished)
                started = True
                await asyncio.shield(task)
                action.finish(ActionState.SUCCEEDED, f"Container {action.operation} completed")
        except (TimeoutError, DockSightError) as exc:
            ambiguous = started and (
                isinstance(exc, TimeoutError)
                or exc.code in {"runtime_timeout", "runtime_unavailable"}
            )
            state = ActionState.INDETERMINATE if ambiguous else ActionState.FAILED
            action.finish(
                state,
                "Docker outcome is unknown; inspect the target before further changes"
                if ambiguous
                else exc.message
                if isinstance(exc, DockSightError)
                else "Action timed out before execution",
            )
        except Exception:
            action.finish(
                ActionState.INDETERMINATE if started else ActionState.FAILED,
                "Action outcome could not be confirmed" if started else "Action execution failed",
            )
        if action.state == ActionState.INDETERMINATE:
            await self.store.block_target(action.host, action.container_id)
        try:
            await self.audit.record(f"action.{action.state}", {**data, "state": action.state.value})
        except Exception:
            action.message += "; audit output is unavailable"

        return action_view(action)

    async def close(self) -> None:
        pending: list[Awaitable[object]] = [*self._tasks.values(), *self._mutations]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
