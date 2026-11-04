import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

from docksight.application.events import TurnEvent
from docksight.application.investigations.contracts import (
    AcceptedTurn,
    DiagnosticCommand,
    QuestionTurn,
    SavedTurn,
    StartTurn,
    TurnError,
    TurnOutcome,
)
from docksight.application.investigations.errors import StorageError
from docksight.application.investigations.lifecycle import conflict, input_digest
from docksight.application.investigations.observations import TurnObservations
from docksight.application.investigations.ports import DiagnosticLease, SelectedDiagnostics, TurnStore
from docksight.application.investigations.service import Investigations
from docksight.application.model_catalog import ModelSelection
from docksight.application.redaction import Redactor
from docksight.domain.errors import DockSightError, ErrorKind

type DiagnosticFactory = Callable[[ModelSelection | None], Awaitable[SelectedDiagnostics]]
type Notification = SavedTurn | DockSightError


class TurnRunner:
    """Own admission and diagnostic tasks independently of request and observer lifetimes."""

    digest = staticmethod(input_digest)

    def __init__(
        self,
        investigations: Investigations,
        turns: TurnStore,
        factory: DiagnosticFactory,
        redactor: Redactor,
        shutdown_timeout: float = 5,
    ) -> None:
        """Retain tasks through commit, registration, persistence, and shutdown cleanup."""
        self.investigations, self.turns, self.factory, self.redactor = investigations, turns, factory, redactor
        self.shutdown_timeout = shutdown_timeout
        self._admissions: set[asyncio.Task[AcceptedTurn]] = set()
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._pending: dict[str, tuple[SavedTurn, DiagnosticLease]] = {}
        self._observers: dict[str, set[asyncio.Queue[Notification]]] = {}
        self._stops: set[str] = set()
        self._interrupts: set[str] = set()
        self._entered: set[str] = set()
        self._actors: dict[str, str] = {}
        self._cancelling: set[str] = set()
        self._closed = False
        self._healthy = True

    async def submit(self, actor: str, command: StartTurn, request_id: str) -> AcceptedTurn:
        """Retain a shielded owner before the first receipt lookup or acceptance write."""
        if self._closed or not self._healthy:
            raise StorageError()
        task = asyncio.create_task(self._admit(actor, command.model_copy(deep=True), request_id))
        self._admissions.add(task)
        task.add_done_callback(self._admission_done)
        return await asyncio.shield(task)

    def _admission_done(self, task: asyncio.Task[AcceptedTurn]) -> None:
        """Retrieve detached request failures and remove only settled admission references."""
        self._admissions.discard(task)
        if not task.cancelled():
            task.exception()

    async def _admit(self, actor: str, command: StartTurn, request_id: str) -> AcceptedTurn:
        """Resolve replay first and own the entire acceptance-to-registration handoff."""
        digest = input_digest(command)
        prior = await self.turns.submission(actor, command.root.submission_id, digest)
        if prior is not None:
            return AcceptedTurn(snapshot=prior, created=False)
        lease: DiagnosticLease | None = None
        try:
            view = await self.investigations.read(actor, command.root.investigation_id)
            self.investigations.validate_host(view.host)
            selected = await self.factory(command.root.model)
            lease = await selected.diagnostics.reserve()
            redacted = self._redacted(command, selected.identity)
            accepted = await self.turns.accept(actor, redacted, digest, request_id, datetime.now(UTC))
        except DockSightError:
            if lease is not None:
                await lease.close()
            prior = await self.turns.submission(actor, command.root.submission_id, digest)
            if prior is not None:
                return AcceptedTurn(snapshot=prior, created=False)
            raise
        except BaseException:
            if lease is not None:
                await lease.close()
            raise
        if not accepted.created:
            await lease.close()
            return accepted
        self._pending[accepted.snapshot.id] = accepted.snapshot, lease
        self._actors[accepted.snapshot.id] = actor
        await self.start(accepted.snapshot.id)
        return accepted

    def _redacted(self, command: StartTurn, identity: ModelSelection | None) -> StartTurn:
        """Detach sanitized input while retaining the separately computed original logical digest."""
        submitted = command.root
        updates: dict[str, object] = {"model": identity}
        if isinstance(submitted, QuestionTurn):
            query = submitted.query.strip()
            if not query or len(query) > 4000:
                raise DockSightError("invalid_query", "Query must contain 1-4000 characters", ErrorKind.VALIDATION)
            updates["query"] = self.redactor.text(query)
        return StartTurn(submitted.model_copy(update=updates, deep=True))

    async def start(self, turn_id: str) -> None:
        """Transfer one accepted lease to a retained worker or durably fail registration."""
        pending = self._pending.pop(turn_id, None)
        if pending is None:
            return
        saved, lease = pending
        try:
            self._jobs[turn_id] = self._register(saved, lease)
        except Exception:
            try:
                await self._terminal(
                    saved,
                    TurnOutcome(
                        expected_revision=saved.revision,
                        state="failed",
                        error=TurnError(code="turn_failed", message="Diagnostic could not be started"),
                    ),
                )
            except BaseException:
                self._healthy = False
                raise
            finally:
                await lease.close()
                self._actors.pop(turn_id, None)
                self._stops.discard(turn_id)

    def _register(self, saved: SavedTurn, lease: DiagnosticLease) -> asyncio.Task[None]:
        """Create an execution task only after acceptance commits and retain its completion handler."""
        work = self._work(saved, lease)
        try:
            task = asyncio.create_task(work)
        except BaseException:
            work.close()
            raise
        task.add_done_callback(lambda completed: self._job_done(saved.id, completed))
        return task

    def _job_done(self, turn_id: str, task: asyncio.Task[None]) -> None:
        """Retrieve uncaught storage failures and wake observers without publishing unsaved success."""
        self._jobs.pop(turn_id, None)
        self._stops.discard(turn_id)
        self._interrupts.discard(turn_id)
        self._entered.discard(turn_id)
        self._actors.pop(turn_id, None)
        self._cancelling.discard(turn_id)
        if task.cancelled() or task.exception() is not None:
            self._healthy = False
            self._publish(turn_id, StorageError())

    def _check_intent(self, turn_id: str, lease: DiagnosticLease) -> None:
        """Recheck explicit cancellation and the monotonic deadline after cancellation-settling writes."""
        if turn_id in self._stops or turn_id in self._interrupts:
            raise asyncio.CancelledError
        if asyncio.get_running_loop().time() >= lease.deadline:
            raise TimeoutError

    async def _work(self, saved: SavedTurn, lease: DiagnosticLease) -> None:
        """Persist each observation and terminal result before publishing revisioned snapshots."""
        self._entered.add(saved.id)
        try:
            context = await self.turns.context(saved.actor, saved.investigation_id)
            command = DiagnosticCommand(
                turn_id=saved.id,
                investigation_id=saved.investigation_id,
                actor=saved.actor,
                host=saved.host,
                query=saved.query,
                target=saved.target,
                identity=saved.model,
                context=context,
            )
            observations = TurnObservations(self.redactor)
            stream = lease.run(command)
            try:
                saved = await self._consume(saved, lease, stream, observations)
            finally:
                await stream.aclose()
            await self._terminal(saved, observations.outcome(saved.revision))
        except asyncio.CancelledError:
            state = "stopped" if saved.id in self._stops else "interrupted"
            await self._settle(saved, state)
        except TimeoutError:
            await self._fail(saved, "turn_timeout", "Diagnostic turn timed out")
        except DockSightError as exc:
            if isinstance(exc, StorageError):
                self._healthy = False
                raise
            await self._fail(saved, exc.code, exc.message)
        except Exception:
            await self._fail(saved, "turn_failed", "Diagnostic failed unexpectedly")
        finally:
            await lease.close()

    async def _consume(
        self, saved: SavedTurn, lease: DiagnosticLease, stream: AsyncIterator[TurnEvent], observations: TurnObservations
    ) -> SavedTurn:
        """Pull more diagnostic work only after progress commits and cancellation checks settle."""
        while True:
            self._check_intent(saved.id, lease)
            try:
                async with asyncio.timeout_at(lease.deadline):
                    event = await anext(stream)
            except StopAsyncIteration:
                return saved
            update = observations.consume(event, saved)
            if update is not None:
                saved = await self.turns.update(saved.actor, saved.id, update, datetime.now(UTC))
                self._publish(saved.id, saved)

    async def _terminal(self, saved: SavedTurn, outcome: TurnOutcome) -> SavedTurn:
        """Commit the terminal result and release durable reservations before notifying observers."""
        try:
            final = await self.turns.finish(saved.actor, saved.id, outcome, datetime.now(UTC))
        except DockSightError as exc:
            if isinstance(exc, StorageError):
                self._healthy = False
            raise
        self._publish(saved.id, final)
        return final

    async def _settle(self, saved: SavedTurn, state: str) -> None:
        """Reread a cancellation-settled revision so terminal races preserve their committed winner."""
        self._cancelling.add(saved.id)
        current = await self.investigations.archive.read_turn(saved.actor, saved.id)
        if current.state == "running":
            outcome = TurnOutcome.model_validate({"expected_revision": current.revision, "state": state})
            await self._terminal(current, outcome)

    async def _fail(self, saved: SavedTurn, code: str, message: str) -> None:
        """Persist a safe failure against the latest revision, including oversized final-result rejection."""
        self._cancelling.add(saved.id)
        current = await self.investigations.archive.read_turn(saved.actor, saved.id)
        if current.state == "running":
            await self._terminal(
                current,
                TurnOutcome(
                    expected_revision=current.revision,
                    state="failed",
                    error=TurnError(code=self.redactor.text(code)[:64], message=self.redactor.text(message)[:512]),
                ),
            )

    def _publish(self, turn_id: str, value: Notification) -> None:
        """Coalesce each slow observer to the newest saved snapshot without blocking execution."""
        for queue in self._observers.get(turn_id, ()):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(value)

    async def observe(self, actor: str, turn_id: str) -> AsyncIterator[SavedTurn]:
        """Attach at most four bounded observers without acquiring any execution ownership."""
        await self.investigations.archive.read_turn(actor, turn_id)
        observers = self._observers.setdefault(turn_id, set())
        if len(observers) == 4:
            raise conflict("turn_observer_capacity", "Diagnostic observer capacity reached")
        queue: asyncio.Queue[Notification] = asyncio.Queue(maxsize=1)
        observers.add(queue)
        revision = -1
        try:
            saved = await self.investigations.archive.read_turn(actor, turn_id)
            while True:
                if saved.revision > revision:
                    yield saved
                    revision = saved.revision
                if saved.state != "running":
                    return
                saved = await self._next_snapshot(queue)
        finally:
            observers.discard(queue)
            if not observers:
                self._observers.pop(turn_id, None)

    async def _next_snapshot(self, queue: asyncio.Queue[Notification]) -> SavedTurn:
        """Fail observers safely when persistence cannot produce another committed snapshot."""
        if not self._healthy:
            raise StorageError()
        value = await queue.get()
        if isinstance(value, DockSightError):
            raise value
        return value

    async def cancel(self, actor: str, turn_id: str) -> SavedTurn:
        """Keep explicit Stop intent through progress commits and await owned-task cleanup."""
        if self._actors.get(turn_id) == actor:
            self._stops.add(turn_id)
            task = self._jobs.get(turn_id)
            if task is not None:
                await self._cancel_job(turn_id, task)
                return await self.investigations.archive.read_turn(actor, turn_id)
        saved = await self.investigations.archive.read_turn(actor, turn_id)
        if saved.state != "running":
            return saved
        self._stops.add(turn_id)
        if self._admissions:
            await asyncio.gather(*(asyncio.shield(task) for task in tuple(self._admissions)), return_exceptions=True)
        task = self._jobs.get(turn_id)
        if task is not None:
            await self._cancel_job(turn_id, task)
        return await self.investigations.archive.read_turn(actor, turn_id)

    async def _cancel_job(self, turn_id: str, task: asyncio.Task[None]) -> None:
        """Share one cancellation request and shield the retained worker through terminal cleanup."""
        self._request_cancel(turn_id, task)
        await asyncio.shield(task)

    def _request_cancel(self, turn_id: str, task: asyncio.Task[None]) -> None:
        """Coalesce Stop and shutdown requests so terminal settlement cannot be cancelled again."""
        if turn_id in self._cancelling:
            return
        self._cancelling.add(turn_id)
        if turn_id in self._entered:
            task.cancel()

    async def close(self) -> None:
        """Drain admissions, allow a short graceful finish, then save remaining jobs as interrupted."""
        self._closed = True
        await asyncio.gather(*tuple(self._admissions), return_exceptions=True)
        jobs = tuple(self._jobs.items())
        if not jobs:
            return
        _, pending = await asyncio.wait([task for _, task in jobs], timeout=self.shutdown_timeout)
        for identity, task in jobs:
            if task in pending:
                self._interrupts.add(identity)
                self._request_cancel(identity, task)
        await asyncio.gather(*(asyncio.shield(task) for _, task in jobs), return_exceptions=True)
