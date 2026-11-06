import asyncio
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest

from docksight.adapters.outbound.memory.investigations import MemoryInvestigations
from docksight.adapters.outbound.memory.turns import MemoryTurnStore
from docksight.application.events import TurnEvent
from docksight.application.investigations.contracts import DiagnosticCommand, QuestionTurn, SavedTurn, StartTurn
from docksight.application.investigations.errors import StorageError
from docksight.application.investigations.ports import SelectedDiagnostics
from docksight.application.investigations.runner import TurnRunner
from docksight.application.investigations.service import Investigations
from docksight.application.model_catalog import ModelSelection
from docksight.application.redaction import Redactor
from docksight.application.views.schemas import GroupTarget
from docksight.domain.errors import DockSightError, ErrorKind


class ControlledDiagnostics:
    """Expose deterministic execution barriers and lease accounting without an external service."""

    def __init__(self) -> None:
        """Record execution and allow tests to release the final answer explicitly."""
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0
        self.continuations = 0
        self.leases = 0
        self.deadline = float("inf")

    async def reserve(self) -> "ControlledDiagnostics":
        """Hold one capacity slot until worker cleanup."""
        self.leases += 1
        return self

    async def run(self, command: DiagnosticCommand) -> AsyncGenerator[TurnEvent]:
        """Wait at a deterministic model boundary before returning a validated answer."""
        self.calls += 1
        self.started.set()
        yield {"type": "tool.started", "turn_id": command.turn_id, "tool": "inspect_host"}
        self.continuations += 1
        await self.release.wait()
        yield {
            "type": "answer.ready",
            "turn_id": command.turn_id,
            "answer": {"summary": "Current evidence", "uncertain": True, "evidence": [], "widgets": []},
        }
        yield {"type": "turn.completed", "turn_id": command.turn_id}

    async def close(self) -> None:
        """Release the held slot after generation and persistence have settled."""
        self.leases -= 1


async def setup_runner() -> tuple[TurnRunner, StartTurn, ControlledDiagnostics]:
    """Construct real memory stores and one controlled diagnostic selection."""
    archive = MemoryInvestigations()
    service = Investigations(archive, lambda: {"local"}, Redactor())
    identity = str(uuid4())
    await service.create("alice", identity, "local")
    source = ControlledDiagnostics()

    async def select(selection: object) -> SelectedDiagnostics:
        """Resolve the test worker without a catalog call."""
        return SelectedDiagnostics(source, None)

    runner = TurnRunner(service, MemoryTurnStore(archive), select, Redactor(), shutdown_timeout=0)
    command = StartTurn(
        QuestionTurn(investigation_id=identity, submission_id=str(uuid4()), expected_revision=0, query="Inspect")
    )
    return runner, command, source


async def test_observer_disconnect_detaches_and_receipt_replays_without_work() -> None:
    runner, command, source = await setup_runner()
    try:
        accepted = await runner.submit("alice", command, "request")
        await source.started.wait()
        observer = runner.observe("alice", accepted.snapshot.id)
        assert (await anext(observer)).state == "running"
        await observer.aclose()
        assert source.calls == 1
        source.release.set()
        snapshots = [saved async for saved in runner.observe("alice", accepted.snapshot.id)]
        assert snapshots[-1].state == "completed" and snapshots[-1].answer is not None
        assert not (await runner.submit("alice", command, "another-request")).created
        assert source.calls == 1
    finally:
        await runner.close()
    assert source.leases == 0


async def test_explicit_stop_cancels_owned_work_and_releases_scope() -> None:
    runner, command, source = await setup_runner()
    try:
        accepted = await runner.submit("alice", command, "request")
        await source.started.wait()
        saved = await runner.cancel("alice", accepted.snapshot.id)
        assert saved.state == "stopped" and source.calls == 1
        assert source.leases == 0
        assert (await runner.cancel("alice", saved.id)).state == "stopped"
    finally:
        await runner.close()


async def test_cancelled_http_after_acceptance_still_registers_owned_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, command, source = await setup_runner()
    committed, register = asyncio.Event(), asyncio.Event()
    original = runner.turns.accept

    async def barrier(*args: object, **kwargs: object) -> object:
        """Pause only after the real acceptance transaction has committed."""
        result = await original(*args, **kwargs)
        committed.set()
        await register.wait()
        return result

    monkeypatch.setattr(runner.turns, "accept", barrier)
    caller = asyncio.create_task(runner.submit("alice", command, "request"))
    try:
        await committed.wait()
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        register.set()
        await source.started.wait()
        source.release.set()
        saved = await runner.turns.submission("alice", command.root.submission_id, runner.digest(command))
        assert saved is not None
        assert [item.state async for item in runner.observe("alice", saved.id)][-1] == "completed"
        assert source.calls == 1
    finally:
        register.set()
        await runner.close()


async def test_shutdown_interrupts_owned_work() -> None:
    runner, command, source = await setup_runner()
    saved = (await runner.submit("alice", command, "request")).snapshot
    await source.started.wait()
    await runner.close()
    assert (await runner.investigations.archive.read_turn("alice", saved.id)).state == "interrupted"
    assert source.leases == 0


async def test_registration_failure_saves_failure_and_releases_reserved_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, command, source = await setup_runner()

    def broken(*args: object) -> None:
        """Reject worker creation at the exact commit-to-registration boundary."""
        raise RuntimeError("registration unavailable")

    monkeypatch.setattr(runner, "_register", broken)
    try:
        accepted = await runner.submit("alice", command, "request")
        saved = await runner.investigations.archive.read_turn("alice", accepted.snapshot.id)
        assert saved.state == "failed" and source.calls == 0 and source.leases == 0
        assert (await runner.investigations.read("alice", command.root.investigation_id)).active_turn_id is None
    finally:
        await runner.close()


async def test_failed_registration_settlement_closes_admission_and_preserves_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, command, source = await setup_runner()

    def broken(*args: object) -> None:
        """Prevent worker registration without starting a coroutine."""
        raise RuntimeError("registration unavailable")

    async def unavailable(*args: object, **kwargs: object) -> None:
        """Fail the terminal write while retaining the accepted row."""
        raise StorageError()

    monkeypatch.setattr(runner, "_register", broken)
    monkeypatch.setattr(runner.turns, "finish", unavailable)
    try:
        with pytest.raises(StorageError):
            await runner.submit("alice", command, "request")
        with pytest.raises(StorageError):
            await runner.submit("alice", command, "request")
        assert (await runner.investigations.read("alice", command.root.investigation_id)).active_turn_id is not None
        assert source.calls == 0 and source.leases == 0
    finally:
        await runner.close()


async def test_replay_bypasses_removed_configuration_unavailable_catalog_and_stale_workspace() -> None:
    runner, command, source = await setup_runner()
    try:
        saved = (await runner.submit("alice", command, "request")).snapshot
        await source.started.wait()

        def removed() -> set[str]:
            """Represent a removed host after the original turn was accepted."""
            return set()

        async def unavailable(selection: object) -> SelectedDiagnostics:
            """Fail if replay incorrectly consults mutable catalog configuration."""
            raise DockSightError("catalog_unavailable", "Catalog unavailable", ErrorKind.UNAVAILABLE)

        runner.investigations.hosts = removed
        runner.factory = unavailable
        replay = command.model_copy(update={"root": command.root.model_copy(update={"expected_revision": 999})})
        assert (await runner.submit("alice", replay, "new-request")).snapshot.id == saved.id
        source.release.set()
        assert [item.state async for item in runner.observe("alice", saved.id)][-1] == "completed"
        assert source.calls == 1
    finally:
        await runner.close()


async def test_concurrent_submissions_register_one_worker_and_release_unused_lease() -> None:
    runner, command, source = await setup_runner()
    try:
        first, second = await asyncio.gather(
            runner.submit("alice", command, "first"), runner.submit("alice", command, "second")
        )
        assert first.snapshot.id == second.snapshot.id and first.created != second.created
        await source.started.wait()
        assert source.calls == 1 and source.leases == 1
        source.release.set()
        assert [item.state async for item in runner.observe("alice", first.snapshot.id)][-1] == "completed"
    finally:
        await runner.close()
    assert source.leases == 0


async def test_observer_capacity_and_coalesced_terminal_snapshot() -> None:
    runner, command, source = await setup_runner()
    observers = []
    try:
        saved = (await runner.submit("alice", command, "req")).snapshot
        await source.started.wait()
        for _ in range(4):
            observer = runner.observe("alice", saved.id)
            assert (await anext(observer)).state == "running"
            observers.append(observer)
        with pytest.raises(DockSightError) as caught:
            await anext(runner.observe("alice", saved.id))
        assert caught.value.code == "turn_observer_capacity"
        source.release.set()
        assert [item.state async for item in observers[0]][-1] == "completed"
        for observer in observers[1:]:
            assert (await anext(observer)).state == "completed"
    finally:
        for observer in observers:
            await observer.aclose()
        await runner.close()


async def test_shutdown_waits_for_inflight_acceptance_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, command, source = await setup_runner()
    committed, release = asyncio.Event(), asyncio.Event()
    original = runner.turns.accept

    async def barrier(*args: object, **kwargs: object) -> object:
        """Hold admission ownership after real acceptance has committed."""
        result = await original(*args, **kwargs)
        committed.set()
        await release.wait()
        return result

    monkeypatch.setattr(runner.turns, "accept", barrier)
    submission = asyncio.create_task(runner.submit("alice", command, "req"))
    await committed.wait()
    shutdown = asyncio.create_task(runner.close())
    release.set()
    accepted = await submission
    await shutdown
    assert (await runner.investigations.archive.read_turn("alice", accepted.snapshot.id)).state == "interrupted"
    assert source.leases == 0


async def test_terminal_storage_failure_never_publishes_success_and_closes_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, command, source = await setup_runner()

    async def unavailable(*args: object, **kwargs: object) -> None:
        """Reject the final write so the buffered answer cannot be published."""
        raise StorageError()

    monkeypatch.setattr(runner.turns, "finish", unavailable)
    try:
        saved = (await runner.submit("alice", command, "req")).snapshot
        await source.started.wait()
        source.release.set()
        observed = []
        with pytest.raises(StorageError):
            async for item in runner.observe("alice", saved.id):
                observed.append(item)
        assert all(item.answer is None and item.state == "running" for item in observed)
        assert (await runner.investigations.archive.read_turn("alice", saved.id)).state == "running"
        with pytest.raises(StorageError):
            await runner.submit("alice", command, "req")
    finally:
        await runner.close()
    assert source.leases == 0


async def test_turn_failure_uses_safe_message_and_releases_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, command, source = await setup_runner()

    async def broken(command: DiagnosticCommand) -> AsyncGenerator[TurnEvent]:
        """Throw private dependency data before a usable answer can be generated."""
        raise RuntimeError("private prompt and reasoning")
        yield {"type": "turn.completed", "turn_id": command.turn_id}

    monkeypatch.setattr(source, "run", broken)
    try:
        saved = (await runner.submit("alice", command, "req")).snapshot
        snapshots = [item async for item in runner.observe("alice", saved.id)]
        assert snapshots[-1].state == "failed"
        assert "private" not in snapshots[-1].model_dump_json()
    finally:
        await runner.close()
    assert source.leases == 0


async def test_validation_error_rechecks_a_concurrently_committed_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, command, source = await setup_runner()
    validating, committed = asyncio.Event(), asyncio.Event()
    original = runner.turns.accept
    calls = 0

    async def selected(selection: object) -> SelectedDiagnostics:
        """Let another validation fail only after identical work has committed."""
        nonlocal calls
        calls += 1
        if calls == 1:
            await validating.wait()
            return SelectedDiagnostics(source, None)
        validating.set()
        await committed.wait()
        raise DockSightError("catalog_unavailable", "Catalog unavailable", ErrorKind.UNAVAILABLE)

    async def accepted(*args: object, **kwargs: object) -> object:
        """Signal a real committed receipt before the competing catalog failure."""
        result = await original(*args, **kwargs)
        committed.set()
        return result

    monkeypatch.setattr(runner.turns, "accept", accepted)
    runner.factory = selected
    try:
        first, second = await asyncio.gather(
            runner.submit("alice", command, "first"), runner.submit("alice", command, "second")
        )
        assert first.snapshot.id == second.snapshot.id and first.created != second.created
        source.release.set()
        assert [item.state async for item in runner.observe("alice", first.snapshot.id)][-1] == "completed"
        assert source.calls == 1
    finally:
        await runner.close()


async def test_digest_precedes_redaction_and_default_model_resolution() -> None:
    runner, command, source = await setup_runner()
    redactor = Redactor(secrets=("private-token",))
    runner.redactor = redactor
    runner.investigations.redactor = redactor
    command = command.model_copy(
        update={"root": command.root.model_copy(update={"query": "  Inspect private-token  "})}
    )

    async def selected(selection: object) -> SelectedDiagnostics:
        """Resolve a server default independently of the original null submitted selection."""
        return SelectedDiagnostics(source, ModelSelection(provider="configured", model="default"))

    runner.factory = selected
    try:
        saved = (await runner.submit("alice", command, "req")).snapshot
        assert saved.query == "Inspect [REDACTED]" and saved.model == ModelSelection(
            provider="configured", model="default"
        )
        assert "private-token" not in saved.model_dump_json()
        assert not (await runner.submit("alice", command, "new-req")).created
        changed = command.model_copy(
            update={"root": command.root.model_copy(update={"query": "Inspect different-token"})}
        )
        with pytest.raises(DockSightError) as conflict:
            await runner.submit("alice", changed, "req")
        assert conflict.value.code == "submission_conflict"
    finally:
        await runner.close()


@pytest.mark.parametrize("changed_policy", ["expanded_query", "sensitive_target"])
async def test_receipt_replay_precedes_changed_redaction_bounds_and_target_validation(changed_policy: str) -> None:
    runner, command, source = await setup_runner()
    submitted = command.root.model_copy(
        update={
            "query": "x" * 1000 if changed_policy == "expanded_query" else "Inspect",
            "target": GroupTarget(kind="compose", name="web") if changed_policy == "sensitive_target" else None,
        }
    )
    command = StartTurn(submitted)
    try:
        saved = (await runner.submit("alice", command, "original-request")).snapshot
        await source.started.wait()
        runner.redactor = Redactor(secrets=("x" if changed_policy == "expanded_query" else "web",))
        fresh = StartTurn(submitted.model_copy(update={"submission_id": str(uuid4()), "expected_revision": 1}))
        with pytest.raises(DockSightError) as invalid:
            await runner.submit("alice", fresh, "fresh-request")
        assert invalid.value.code == ("invalid_query" if changed_policy == "expanded_query" else "invalid_target")
        replay = await runner.submit("alice", command, "replay-request")
        assert not replay.created and replay.snapshot.id == saved.id
        assert replay.snapshot.request_id == "original-request"
        assert source.calls == 1 and source.leases == 1
    finally:
        await runner.close()


async def test_completion_and_stop_share_one_terminal_winner() -> None:
    runner, command, source = await setup_runner()
    try:
        saved = (await runner.submit("alice", command, "req")).snapshot
        await source.started.wait()
        source.release.set()
        stopped, snapshots = await asyncio.gather(runner.cancel("alice", saved.id), collect_snapshots(runner, saved.id))
        final = await runner.investigations.archive.read_turn("alice", saved.id)
        assert final.state in {"completed", "stopped"} and stopped == final and snapshots[-1] == final
        context = await runner.turns.context("alice", saved.investigation_id)
        assert len(context) == (2 if final.state == "completed" else 0)
        assert source.calls == 1
    finally:
        await runner.close()


async def collect_snapshots(runner: TurnRunner, turn_id: str) -> list[object]:
    """Collect one owned observer to compare its terminal result with a simultaneous Stop."""
    return [saved async for saved in runner.observe("alice", turn_id)]


@pytest.mark.parametrize("query", ["   ", "x" * 4001], ids=["blank", "overlong"])
async def test_invalid_trimmed_question_is_a_validation_error_before_acceptance(query: str) -> None:
    runner, command, source = await setup_runner()
    command = command.model_copy(update={"root": command.root.model_copy(update={"query": query})})
    try:
        with pytest.raises(DockSightError) as caught:
            await runner.submit("alice", command, "req")
        assert caught.value.code == "invalid_query" and caught.value.kind == ErrorKind.VALIDATION
        assert (await runner.investigations.read("alice", command.root.investigation_id)).turn_count == 0
        assert source.calls == 0 and source.leases == 0
    finally:
        await runner.close()


@pytest.mark.parametrize("followup", ["stop", "shutdown", "cancelled_stop"])
async def test_terminal_cleanup_survives_repeated_cancellation_requests(
    monkeypatch: pytest.MonkeyPatch,
    followup: str,
) -> None:
    runner, command, source = await setup_runner()
    entered, release = asyncio.Event(), asyncio.Event()
    archive = runner.investigations.archive
    original = archive.read_turn

    async def paused_read(actor: str, turn_id: str) -> SavedTurn:
        """Pause the cancellation settlement read before any storage operation is admitted."""
        entered.set()
        await release.wait()
        return await original(actor, turn_id)

    callers = []
    try:
        saved = (await runner.submit("alice", command, "req")).snapshot
        await source.started.wait()
        monkeypatch.setattr(archive, "read_turn", paused_read)
        first = asyncio.create_task(runner.cancel("alice", saved.id))
        callers.append(first)
        await asyncio.wait_for(entered.wait(), 2)
        second = asyncio.create_task(runner.close() if followup == "shutdown" else runner.cancel("alice", saved.id))
        callers.append(second)
        await asyncio.sleep(0)
        if followup == "shutdown":
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(second), 0.05)
        if followup == "cancelled_stop":
            second.cancel()
            with pytest.raises(asyncio.CancelledError):
                await second
        assert source.leases == 1
        release.set()
        assert (await asyncio.wait_for(first, 2)).state == "stopped"
        if followup == "stop":
            assert (await second).state == "stopped"
        elif followup == "shutdown":
            await second
        final = await original("alice", saved.id)
        assert final.state == "stopped" and final.revision == 2
        assert (await runner.investigations.read("alice", saved.investigation_id)).active_turn_id is None
        assert source.calls == 1 and source.leases == 0
    finally:
        release.set()
        await asyncio.gather(*callers, return_exceptions=True)
        await runner.close()


async def test_cancelled_stop_owner_leaves_terminal_cleanup_retained(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, command, source = await setup_runner()
    entered, release = asyncio.Event(), asyncio.Event()
    archive = runner.investigations.archive
    original = archive.read_turn

    async def paused_read(actor: str, turn_id: str) -> SavedTurn:
        """Wait before terminal persistence while the originating Stop caller disconnects."""
        entered.set()
        await release.wait()
        return await original(actor, turn_id)

    caller = None
    try:
        saved = (await runner.submit("alice", command, "req")).snapshot
        await source.started.wait()
        monkeypatch.setattr(archive, "read_turn", paused_read)
        caller = asyncio.create_task(runner.cancel("alice", saved.id))
        await asyncio.wait_for(entered.wait(), 2)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert source.leases == 1
        release.set()
        assert (await asyncio.wait_for(runner.cancel("alice", saved.id), 2)).state == "stopped"
        assert source.leases == 0
        assert (await runner.investigations.read("alice", saved.investigation_id)).active_turn_id is None
    finally:
        release.set()
        if caller is not None:
            await asyncio.gather(caller, return_exceptions=True)
        await runner.close()


async def test_unexpected_cancelled_worker_closes_admission_and_retains_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, command, source = await setup_runner()

    async def broken_settlement(saved: SavedTurn, state: str) -> None:
        """Represent an unexpected cancellation before the terminal outcome can be saved."""
        raise asyncio.CancelledError

    monkeypatch.setattr(runner, "_settle", broken_settlement)
    try:
        saved = (await runner.submit("alice", command, "req")).snapshot
        await source.started.wait()
        with pytest.raises(asyncio.CancelledError):
            await runner.cancel("alice", saved.id)
        with pytest.raises(StorageError):
            await runner.submit("alice", command, "new-req")
        assert (await runner.investigations.read("alice", saved.investigation_id)).active_turn_id == saved.id
        assert source.leases == 0
    finally:
        await runner.close()
