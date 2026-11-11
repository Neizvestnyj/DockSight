import asyncio
import os
import sys
import threading
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

import pytest

from docksight.adapters.outbound.memory.investigations import MemoryInvestigations
from docksight.adapters.outbound.memory.turns import MemoryTurnStore
from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.adapters.outbound.persistence.investigations import SQLiteInvestigations
from docksight.adapters.outbound.persistence.recovery import recover_actions, recover_investigations
from docksight.adapters.outbound.persistence.turns import SQLiteTurnStore
from docksight.application.diagnostics.trace import TraceStep
from docksight.application.investigations.contracts import (
    ClarificationTurn,
    QuestionTurn,
    SavedTurn,
    StartTurn,
    StorageLimits,
    TurnOutcome,
    TurnUpdate,
    WorkspacePatch,
)
from docksight.application.investigations.errors import HistoryError
from docksight.application.investigations.ports import InvestigationArchive, SelectedDiagnostics, TurnStore
from docksight.application.investigations.runner import TurnRunner
from docksight.application.investigations.service import Investigations
from docksight.application.redaction import Redactor
from docksight.application.views.schemas import DiagnosisResponse, GroupTarget, TargetSelection
from tests.unit.application.investigations.test_runner import ControlledDiagnostics

NOW: Final = datetime(2026, 11, 3, tzinfo=UTC)
WORKER_PATH: Final = str(Path(__file__).resolve())


@pytest.fixture(params=["memory", "sqlite"])
async def stores(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[tuple[InvestigationArchive, TurnStore]]:
    """Exercise the same lifecycle contract against both real state adapters."""
    if request.param == "memory":
        archive = MemoryInvestigations()
        yield archive, MemoryTurnStore(archive)
        return
    database = PersistentDatabase(tmp_path / "state.sqlite3", recoveries=(recover_actions, recover_investigations))
    await database.initialize_server()
    try:
        yield SQLiteInvestigations(database), SQLiteTurnStore(database)
    finally:
        await database.close()


def question(identity: str, revision: int = 0, query: str = "Inspect") -> StartTurn:
    """Build a fresh logical submission for an acknowledged workspace revision."""
    return StartTurn(
        QuestionTurn(investigation_id=identity, submission_id=str(uuid4()), expected_revision=revision, query=query)
    )


def answer(summary: str = "Observed current evidence") -> DiagnosisResponse:
    """Provide a valid no-card uncertain diagnosis without model or runtime calls."""
    return DiagnosisResponse(summary=summary, uncertain=True, evidence=[], widgets=[])


async def test_receipts_win_over_stale_revision_scope_and_capacity(
    stores: tuple[InvestigationArchive, TurnStore],
) -> None:
    archive, turns = stores
    identity = str(uuid4())
    await archive.create("alice", identity, "local", NOW)
    command = question(identity)
    accepted = await turns.accept("alice", command, "a" * 64, "request", NOW)
    duplicate = await turns.accept("alice", command, "a" * 64, "different-request", NOW)
    assert duplicate.snapshot == accepted.snapshot and not duplicate.created
    assert await turns.submission("alice", command.root.submission_id, "a" * 64) == accepted.snapshot
    with pytest.raises(HistoryError, match="different input"):
        await turns.submission("alice", command.root.submission_id, "b" * 64)
    with pytest.raises(HistoryError) as busy:
        await turns.accept("alice", question(identity, 1), "c" * 64, "request", NOW)
    assert busy.value.code == "turn_busy"
    assert await turns.submission("bob", command.root.submission_id, "a" * 64) is None


async def test_terminal_cas_releases_scope_and_delete_keeps_receipt(
    stores: tuple[InvestigationArchive, TurnStore],
) -> None:
    archive, turns = stores
    identity = str(uuid4())
    await archive.create("alice", identity, "local", NOW)
    command = question(identity)
    running = (await turns.accept("alice", command, "a" * 64, "request", NOW)).snapshot
    final = await turns.finish(
        "alice", running.id, TurnOutcome(expected_revision=0, state="completed", answer=answer()), NOW
    )
    assert final.state == "completed" and final.revision == 1 and final.finished_at == NOW
    with pytest.raises(HistoryError) as conflict:
        await turns.update("alice", running.id, TurnUpdate(expected_revision=0), NOW)
    assert conflict.value.code == "turn_conflict"
    await archive.delete("alice", identity, NOW)
    with pytest.raises(HistoryError) as deleted:
        await turns.submission("alice", command.root.submission_id, "a" * 64)
    assert deleted.value.code == "history_deleted"


async def test_archive_keeps_all_turns_while_context_trims_whole_pairs(
    stores: tuple[InvestigationArchive, TurnStore],
) -> None:
    archive, turns = stores
    identity = str(uuid4())
    await archive.create("alice", identity, "local", NOW)
    for index in range(12):
        saved = (
            await turns.accept("alice", question(identity, index, f"Question {index}"), f"{index:064x}", "req", NOW)
        ).snapshot
        await turns.finish(
            "alice", saved.id, TurnOutcome(expected_revision=0, state="completed", answer=answer(str(index))), NOW
        )
    assert (await archive.read("alice", identity)).turn_count == 12
    context = await turns.context("alice", identity)
    assert len(context) == 20 and context[0].content == "Question 2"
    saved = (await turns.accept("alice", question(identity, 12, "x" * 8000), "f" * 64, "req", NOW)).snapshot
    await turns.finish(
        "alice", saved.id, TurnOutcome(expected_revision=0, state="completed", answer=answer("y" * 30000)), NOW
    )
    assert await turns.context("alice", identity) == ()


async def test_clarification_inherits_question_and_accepts_one_child(
    stores: tuple[InvestigationArchive, TurnStore],
) -> None:
    archive, turns = stores
    identity = str(uuid4())
    await archive.create("alice", identity, "local", NOW)
    parent = (await turns.accept("alice", question(identity), "a" * 64, "req", NOW)).snapshot
    target = GroupTarget(kind="compose", name="web")
    await turns.finish(
        "alice",
        parent.id,
        TurnOutcome(expected_revision=0, state="awaiting_selection", selection=TargetSelection(candidates=[target])),
        NOW,
    )
    child_input = StartTurn(
        ClarificationTurn(
            investigation_id=identity,
            submission_id=str(uuid4()),
            expected_revision=1,
            clarification_of=parent.id,
            expected_parent_revision=1,
            target=target,
        )
    )
    child = (await turns.accept("alice", child_input, "b" * 64, "req", NOW)).snapshot
    assert child.query == parent.query and child.clarification_of == parent.id and child.target == target
    assert (await archive.read_turn("alice", parent.id)).resolved_by_turn_id == child.id
    assert not (await turns.accept("alice", child_input, "b" * 64, "req", NOW)).created
    await turns.finish("alice", child.id, TurnOutcome(expected_revision=0, state="stopped"), NOW)
    another = child_input.model_copy(
        update={"root": child_input.root.model_copy(update={"submission_id": str(uuid4()), "expected_revision": 2})}
    )
    with pytest.raises(HistoryError) as conflict:
        await turns.accept("alice", another, "c" * 64, "req", NOW)
    assert conflict.value.code == "clarification_conflict"
    assert await turns.context("alice", identity) == ()


async def test_restart_interrupts_running_turn_without_resuming(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    database = PersistentDatabase(path, recoveries=(recover_actions, recover_investigations))
    await database.initialize_server()
    archive, turns = SQLiteInvestigations(database), SQLiteTurnStore(database)
    identity = str(uuid4())
    await archive.create("alice", identity, "local", NOW)
    saved = (await turns.accept("alice", question(identity), "a" * 64, "req", NOW)).snapshot
    await database.close()
    reopened = PersistentDatabase(path, recoveries=(recover_actions, recover_investigations))
    try:
        report = await reopened.initialize_server()
        assert report.interrupted_turns == 1
        assert (await SQLiteInvestigations(reopened).read_turn("alice", saved.id)).state == "interrupted"
        assert (await SQLiteInvestigations(reopened).read("alice", identity)).active_turn_id is None
    finally:
        await reopened.close()


async def test_stop_during_sqlite_progress_commit_never_starts_next_diagnostic_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from docksight.adapters.outbound.persistence import turns as persistence

    database = PersistentDatabase(tmp_path / "state.sqlite3", recoveries=(recover_actions, recover_investigations))
    await database.initialize_server()
    archive, store = SQLiteInvestigations(database), SQLiteTurnStore(database)
    service = Investigations(archive, lambda: {"local"}, Redactor())
    identity = str(uuid4())
    await service.create("alice", identity, "local")
    source = ControlledDiagnostics()

    async def select(selection: object) -> SelectedDiagnostics:
        """Resolve deterministic fake diagnostics without a model or catalog request."""
        return SelectedDiagnostics(source, None)

    runner = TurnRunner(service, store, select, Redactor(), shutdown_timeout=0)
    entered, release = threading.Event(), threading.Event()
    original = persistence.save_turn

    def paused_save(row: object, saved: object, maximum: int = 2097152) -> None:
        """Hold an actual worker transaction after progress changes and before commit."""
        original(row, saved, maximum)
        if saved.state == "running" and saved.revision == 1:
            entered.set()
            assert release.wait(5)

    monkeypatch.setattr(persistence, "save_turn", paused_save)
    stop = None
    try:
        accepted = await runner.submit("alice", question(identity), "request")
        assert await asyncio.to_thread(entered.wait, 2)
        stop = asyncio.create_task(runner.cancel("alice", accepted.snapshot.id))
        await asyncio.sleep(0)
        release.set()
        assert (await stop).state == "stopped"
        assert source.continuations == 0
        assert (await archive.read("alice", identity)).active_turn_id is None
    finally:
        release.set()
        if stop is not None:
            await asyncio.gather(stop, return_exceptions=True)
        await runner.close()
        await database.close()


async def test_sqlite_acceptance_commit_survives_http_cancellation_until_worker_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = PersistentDatabase(tmp_path / "state.sqlite3", recoveries=(recover_actions, recover_investigations))
    await database.initialize_server()
    archive, store = SQLiteInvestigations(database), SQLiteTurnStore(database)
    service = Investigations(archive, lambda: {"local"}, Redactor())
    identity = str(uuid4())
    await service.create("alice", identity, "local")
    source = ControlledDiagnostics()

    async def select(selection: object) -> SelectedDiagnostics:
        """Select a deterministic worker before the acceptance transaction begins."""
        return SelectedDiagnostics(source, None)

    runner = TurnRunner(service, store, select, Redactor(), shutdown_timeout=0)
    committed, release = asyncio.Event(), asyncio.Event()
    original = store.accept

    async def paused_accept(*args: object, **kwargs: object) -> object:
        """Keep the admission owner alive after the real SQLite commit and before registration."""
        accepted = await original(*args, **kwargs)
        committed.set()
        await release.wait()
        return accepted

    monkeypatch.setattr(store, "accept", paused_accept)
    command = question(identity)
    caller = asyncio.create_task(runner.submit("alice", command, "req"))
    try:
        await committed.wait()
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert (await archive.read("alice", identity)).active_turn_id is not None
        release.set()
        await source.started.wait()
        source.release.set()
        saved = await store.submission("alice", command.root.submission_id, runner.digest(command))
        assert saved is not None
        assert [item.state async for item in runner.observe("alice", saved.id)][-1] == "completed"
        assert source.calls == 1
    finally:
        release.set()
        await runner.close()
        await database.close()


@pytest.mark.parametrize("followup", ["stop", "shutdown"])
async def test_terminal_settlement_retains_ownership_across_repeated_stop_or_shutdown(
    stores: tuple[InvestigationArchive, TurnStore],
    monkeypatch: pytest.MonkeyPatch,
    followup: str,
) -> None:
    archive, store = stores
    service = Investigations(archive, lambda: {"local"}, Redactor())
    identity = str(uuid4())
    await service.create("alice", identity, "local")
    source = ControlledDiagnostics()

    async def selected(selection: object) -> SelectedDiagnostics:
        """Use a deterministic diagnostic worker with observable lease ownership."""
        return SelectedDiagnostics(source, None)

    runner = TurnRunner(service, store, selected, Redactor(), shutdown_timeout=0)
    entered, release = asyncio.Event(), asyncio.Event()
    original = archive.read_turn

    async def paused_read(actor: str, turn_id: str) -> SavedTurn:
        """Hold terminal settlement before the real store's cancellable read admission."""
        entered.set()
        await release.wait()
        return await original(actor, turn_id)

    callers = []
    try:
        command = question(identity)
        saved = (await runner.submit("alice", command, "req")).snapshot
        await source.started.wait()
        monkeypatch.setattr(archive, "read_turn", paused_read)
        first = asyncio.create_task(runner.cancel("alice", saved.id))
        callers.append(first)
        await asyncio.wait_for(entered.wait(), 2)
        second = asyncio.create_task(runner.close() if followup == "shutdown" else runner.cancel("alice", saved.id))
        callers.append(second)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(second), 0.05)
        assert source.leases == 1
        release.set()
        assert (await asyncio.wait_for(first, 2)).state == "stopped"
        await second
        assert (await original("alice", saved.id)).state == "stopped"
        assert (await archive.read("alice", identity)).active_turn_id is None
        assert await store.context("alice", identity) == ()
        assert source.calls == 1 and source.leases == 0
    finally:
        release.set()
        await asyncio.gather(*callers, return_exceptions=True)
        await runner.close()


def apply_limits(archive: InvestigationArchive, turns: TurnStore, limits: StorageLimits) -> None:
    """Apply one explicit capacity policy to both views of the test adapter."""
    archive.limits = limits
    if isinstance(turns, SQLiteTurnStore):
        turns.limits = limits
        turns.archive.limits = limits


async def test_reserved_snapshot_capacity_blocks_draft_growth_until_terminal_release(
    stores: tuple[InvestigationArchive, TurnStore],
) -> None:
    archive, turns = stores
    apply_limits(archive, turns, StorageLimits(snapshot_bytes=4096, investigation_bytes=5000, actor_bytes=10000))
    identity = str(uuid4())
    await archive.create("alice", identity, "local", NOW)
    command = question(identity)
    saved = (await turns.accept("alice", command, "a" * 64, "req", NOW)).snapshot
    with pytest.raises(HistoryError) as quota:
        await archive.patch_workspace("alice", identity, WorkspacePatch(expected_revision=1, draft="x" * 1000), NOW)
    assert quota.value.code == "history_capacity"
    with pytest.raises(HistoryError) as oversized:
        await turns.finish(
            "alice", saved.id, TurnOutcome(expected_revision=0, state="completed", answer=answer("x" * 5000)), NOW
        )
    assert oversized.value.code == "history_capacity"
    assert (await archive.read_turn("alice", saved.id)).state == "running"
    assert await turns.context("alice", identity) == ()
    await turns.finish("alice", saved.id, TurnOutcome(expected_revision=0, state="stopped"), NOW)
    assert (
        await archive.patch_workspace("alice", identity, WorkspacePatch(expected_revision=1, draft="x" * 1000), NOW)
    ).revision == 2
    apply_limits(archive, turns, StorageLimits(snapshot_bytes=1, investigation_bytes=1, actor_bytes=1))
    assert not (await turns.accept("alice", command, "a" * 64, "req", NOW)).created


async def test_capacity_rejection_leaves_no_receipt_draft_clear_or_active_scope(
    stores: tuple[InvestigationArchive, TurnStore],
) -> None:
    archive, turns = stores
    identity = str(uuid4())
    await archive.create("alice", identity, "local", NOW)
    apply_limits(archive, turns, StorageLimits(snapshot_bytes=1))
    command = question(identity)
    before = await archive.read("alice", identity)
    with pytest.raises(HistoryError) as caught:
        await turns.accept("alice", command, "a" * 64, "req", NOW)
    assert caught.value.code == "history_capacity"
    assert await archive.read("alice", identity) == before
    assert await turns.submission("alice", command.root.submission_id, "a" * 64) is None


@pytest.mark.parametrize("draft", ["Different acknowledged draft", "Inspect"])
async def test_acceptance_clears_only_the_matching_acknowledged_question_draft(
    stores: tuple[InvestigationArchive, TurnStore],
    draft: str,
) -> None:
    archive, turns = stores
    identity = str(uuid4())
    await archive.create("alice", identity, "local", NOW)
    await archive.patch_workspace("alice", identity, WorkspacePatch(expected_revision=0, draft=draft), NOW)
    await turns.accept("alice", question(identity, revision=1), "a" * 64, "req", NOW)
    workspace = (await archive.read("alice", identity)).workspace
    assert workspace.draft == ("" if draft == "Inspect" else draft)


async def test_scope_is_actor_and_host_bound_and_foreign_writes_are_rejected(
    stores: tuple[InvestigationArchive, TurnStore],
) -> None:
    archive, turns = stores
    first, second, remote, foreign = (str(uuid4()) for _ in range(4))
    for identity, actor, host in [
        (first, "alice", "local"),
        (second, "alice", "local"),
        (remote, "alice", "remote"),
        (foreign, "bob", "local"),
    ]:
        await archive.create(actor, identity, host, NOW)
    saved = (await turns.accept("alice", question(first), "a" * 64, "req", NOW)).snapshot
    with pytest.raises(HistoryError) as busy:
        await turns.accept("alice", question(second), "b" * 64, "req", NOW)
    assert busy.value.code == "turn_busy"
    assert (await turns.accept("alice", question(remote), "c" * 64, "req", NOW)).created
    assert (await turns.accept("bob", question(foreign), "d" * 64, "req", NOW)).created
    for actor in ["bob", "missing"]:
        with pytest.raises(HistoryError) as denied:
            await turns.update(actor, saved.id, TurnUpdate(expected_revision=0), NOW)
        assert denied.value.code == "history_not_found"


@pytest.mark.parametrize("change", ["stale_parent", "foreign_candidate", "wrong_investigation"])
async def test_clarification_rejection_preserves_parent_and_starts_no_child(
    stores: tuple[InvestigationArchive, TurnStore],
    change: str,
) -> None:
    archive, turns = stores
    identity = str(uuid4())
    await archive.create("alice", identity, "local", NOW)
    parent = (await turns.accept("alice", question(identity), "a" * 64, "req", NOW)).snapshot
    target = GroupTarget(kind="compose", name="web")
    await turns.finish(
        "alice",
        parent.id,
        TurnOutcome(expected_revision=0, state="awaiting_selection", selection=TargetSelection(candidates=[target])),
        NOW,
    )
    child_identity = identity
    if change == "wrong_investigation":
        child_identity = str(uuid4())
        await archive.create("alice", child_identity, "local", NOW)
    child = StartTurn(
        ClarificationTurn(
            investigation_id=child_identity,
            submission_id=str(uuid4()),
            expected_revision=1 if child_identity == identity else 0,
            clarification_of=parent.id,
            expected_parent_revision=0 if change == "stale_parent" else 1,
            target=GroupTarget(kind="compose", name="foreign") if change == "foreign_candidate" else target,
        )
    )
    with pytest.raises(HistoryError):
        await turns.accept("alice", child, "b" * 64, "req", NOW)
    assert (await archive.read_turn("alice", parent.id)).resolved_by_turn_id is None
    assert (await archive.read("alice", child_identity)).active_turn_id is None
    assert await turns.submission("alice", child.root.submission_id, "b" * 64) is None


@pytest.mark.parametrize("barrier", ["acceptance", "progress"])
async def test_killed_process_recovers_committed_diagnostics_without_model_resumption(
    tmp_path: Path, barrier: str
) -> None:
    path = tmp_path / "state.sqlite3"
    identity, submission_id = str(uuid4()), str(uuid4())
    backend = Path(__file__).parents[2]
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join((str(backend / "src"), str(backend)))}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        WORKER_PATH,
        str(path),
        identity,
        submission_id,
        barrier,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    try:
        assert process.stdout is not None
        async with asyncio.timeout(20):
            ready = await process.stdout.readline()
        assert ready.strip() == b"READY"
    finally:
        if process.returncode is None:
            process.kill()
        await process.communicate()
    for restart in range(2):
        database = PersistentDatabase(path, recoveries=(recover_actions, recover_investigations))
        try:
            report = await database.initialize_server()
            assert report.interrupted_turns == (1 if restart == 0 else 0)
            saved = await SQLiteTurnStore(database).submission("alice", submission_id, "a" * 64)
            assert saved is not None and saved.state == "interrupted" and saved.finished_at is not None
            assert (await SQLiteInvestigations(database).read("alice", identity)).active_turn_id is None
            assert await SQLiteTurnStore(database).context("alice", identity) == ()
            if barrier == "progress":
                assert saved.trace[0].state == "running" and saved.trace[0].finished_at is None
                assert saved.trace[0].duration_ms is None
        finally:
            await database.close()


async def crash_worker(path: Path, identity: str, submission_id: str, barrier: str) -> None:
    """Wait after a real SQLite commit until the parent kills this independent backend process."""
    database = PersistentDatabase(path, recoveries=(recover_actions, recover_investigations))
    await database.initialize_server()
    await SQLiteInvestigations(database).create("alice", identity, "local", NOW)
    command = StartTurn(
        QuestionTurn(investigation_id=identity, submission_id=submission_id, expected_revision=0, query="Inspect")
    )
    store = SQLiteTurnStore(database)
    saved = (await store.accept("alice", command, "a" * 64, "req", NOW)).snapshot
    if barrier == "progress":
        step = TraceStep(id="step-1", kind="model", operation="collect_evidence", started_at=NOW)
        await store.update("alice", saved.id, TurnUpdate(expected_revision=0, trace=(step,)), NOW)
    print("READY", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(crash_worker(Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]))
