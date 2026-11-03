from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from docksight.adapters.outbound.memory.investigations import MemoryInvestigations, MemoryTurn
from docksight.adapters.outbound.persistence.codec import utc_text
from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.adapters.outbound.persistence.investigations import SQLiteInvestigations
from docksight.adapters.outbound.persistence.rows import TurnRow
from docksight.application.investigations.contracts import (
    ActorWorkspacePatch,
    SavedTurn,
    StorageLimits,
    UnsupportedTurn,
    WorkspacePatch,
)
from docksight.application.investigations.errors import HistoryError, WorkspaceConflict
from docksight.application.investigations.ports import InvestigationArchive

NOW = datetime(2026, 11, 3, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
async def archive(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[InvestigationArchive]:
    """Exercise the same detached archive boundary with both real adapters."""
    if request.param == "memory":
        yield MemoryInvestigations()
        return
    database = PersistentDatabase(tmp_path / "state.sqlite3")
    await database.initialize_server()
    try:
        yield SQLiteInvestigations(database)
    finally:
        await database.close()


async def test_archive_scopes_creation_reads_and_idempotency(archive: InvestigationArchive) -> None:
    identity = str(uuid4())
    initial = await archive.create("alice", identity, "local", NOW)
    assert initial.host == "local"
    assert await archive.create("alice", identity, "local", NOW) == initial
    for actor, host in [("bob", "local"), ("alice", "other")]:
        with pytest.raises(HistoryError):
            await archive.create(actor, identity, host, NOW)
    with pytest.raises(HistoryError, match="not found"):
        await archive.read("bob", identity)
    with pytest.raises(HistoryError, match="not found"):
        await archive.turns("bob", identity)


async def test_pagination_keeps_older_archives_and_scopes_cursors(archive: InvestigationArchive) -> None:
    identities = [str(uuid4()) for _ in range(12)]
    for index, identity in enumerate(identities):
        await archive.create("alice", identity, "local", NOW + timedelta(seconds=index))
    page = await archive.list_owned("alice")
    assert len(page.items) == 10
    assert page.items[0].id == identities[-1]
    assert page.next_cursor
    older = await archive.list_owned("alice", cursor=page.next_cursor)
    assert [row.id for row in older.items] == identities[1::-1]
    with pytest.raises(HistoryError) as caught:
        await archive.list_owned("bob", cursor=page.next_cursor)
    assert caught.value.code == "history_cursor"


async def test_workspace_cas_and_actor_preferences(archive: InvestigationArchive) -> None:
    identity = str(uuid4())
    await archive.create("alice", identity, "local", NOW)
    saved = await archive.patch_workspace("alice", identity, WorkspacePatch(expected_revision=0, draft="safe"), NOW)
    assert saved.revision == 1
    with pytest.raises(WorkspaceConflict) as caught:
        await archive.patch_workspace("alice", identity, WorkspacePatch(expected_revision=0, draft="stale"), NOW)
    assert caught.value.current == saved
    actor = await archive.patch_actor_workspace(
        "alice", ActorWorkspacePatch(expected_revision=0, last_investigation_id=identity, host="local"), NOW
    )
    assert actor.revision == 1
    with pytest.raises(WorkspaceConflict):
        await archive.patch_actor_workspace("alice", ActorWorkspacePatch(expected_revision=0, host="other"), NOW)
    assert (await archive.workspace("bob")).last_investigation_id is None
    with pytest.raises(HistoryError):
        await archive.patch_actor_workspace(
            "bob", ActorWorkspacePatch(expected_revision=0, last_investigation_id=identity), NOW
        )


async def test_deletion_selects_next_owned_archive(archive: InvestigationArchive) -> None:
    older, active = str(uuid4()), str(uuid4())
    await archive.create("alice", older, "local", NOW)
    await archive.create("alice", active, "local", NOW + timedelta(seconds=1))
    await archive.patch_actor_workspace(
        "alice", ActorWorkspacePatch(expected_revision=0, last_investigation_id=active), NOW
    )
    await archive.delete("alice", active, NOW)
    assert (await archive.workspace("alice")).last_investigation_id == older
    with pytest.raises(HistoryError):
        await archive.read("alice", active)


async def seed_turn(archive: InvestigationArchive, snapshot: SavedTurn, *, unsupported: bool = False) -> None:
    """Seed bounded snapshots without implementing the later diagnostic admission contract."""
    encoded = snapshot.model_dump_json()
    if unsupported:
        encoded = encoded.replace('"schema_version":1', '"schema_version":99')
    if isinstance(archive, MemoryInvestigations):
        archive._turns[snapshot.id] = MemoryTurn(
            snapshot.investigation_id, utc_text(snapshot.created_at), encoded, snapshot.state
        )
        return
    assert isinstance(archive, SQLiteInvestigations)
    await archive.database.transaction(
        lambda session: session.add(
            TurnRow(
                id=snapshot.id,
                investigation_id=snapshot.investigation_id,
                actor=snapshot.actor,
                host=snapshot.host,
                submission_id=snapshot.submission_id,
                input_digest="a" * 64,
                request_id=snapshot.request_id,
                state=snapshot.state,
                revision=snapshot.revision,
                created_at=utc_text(snapshot.created_at),
                updated_at=utc_text(snapshot.updated_at),
                snapshot=encoded,
                snapshot_bytes=len(encoded.encode()),
            )
        ),
        write=True,
    )


def saved_turn(identity: str, index: int = 0) -> SavedTurn:
    """Create a safe stopped snapshot with deterministic chronological placement."""
    return SavedTurn(
        id=str(uuid4()),
        investigation_id=identity,
        actor="alice",
        host="local",
        submission_id=str(uuid4()),
        request_id="original-request",
        query="Why is the API stopped?",
        state="stopped",
        created_at=NOW + timedelta(seconds=index),
        updated_at=NOW + timedelta(seconds=index),
    )


async def test_older_turn_pages_and_foreign_reads(archive: InvestigationArchive) -> None:
    identity = str(uuid4())
    await archive.create("alice", identity, "local", NOW)
    snapshots = [saved_turn(identity, index) for index in range(24)]
    for snapshot in snapshots:
        await seed_turn(archive, snapshot)
    newest = await archive.turns("alice", identity)
    assert [item.id for item in newest.items] == [item.id for item in snapshots[4:]]
    older = await archive.turns("alice", identity, cursor=newest.next_cursor)
    assert [item.id for item in older.items] == [item.id for item in snapshots[:4]]
    assert (await archive.read("alice", identity)).turn_count == 24
    with pytest.raises(HistoryError):
        await archive.read_turn("bob", snapshots[0].id)
    with pytest.raises(HistoryError):
        await archive.read_turn("alice", str(uuid4()))
    other = str(uuid4())
    await archive.create("alice", other, "local", NOW)
    with pytest.raises(HistoryError):
        await archive.turns("alice", other, cursor=newest.next_cursor)


async def test_unsupported_snapshot_remains_a_per_item_error(archive: InvestigationArchive) -> None:
    identity = str(uuid4())
    await archive.create("alice", identity, "local", NOW)
    snapshot = saved_turn(identity)
    await seed_turn(archive, snapshot, unsupported=True)
    with pytest.raises(HistoryError) as caught:
        await archive.read_turn("alice", snapshot.id)
    assert caught.value.code == "history_unsupported"
    page = await archive.turns("alice", identity)
    assert page.items == (UnsupportedTurn(id=snapshot.id),)
    assert (await archive.turns("alice", identity)).items == page.items
    await archive.delete("alice", identity, NOW)
    with pytest.raises(HistoryError):
        await archive.read_turn("alice", snapshot.id)


async def test_returned_nested_values_are_detached(archive: InvestigationArchive) -> None:
    identity = str(uuid4())
    await archive.create("alice", identity, "local", NOW)
    changed = await archive.patch_workspace(
        "alice",
        identity,
        WorkspacePatch.model_validate({"expected_revision": 0, "target": {"kind": "compose", "name": "api"}}),
        NOW,
    )
    assert changed.target is not None
    changed.target.kind = "swarm"
    current = await archive.read("alice", identity)
    assert current.workspace.target is not None
    assert current.workspace.target.kind == "compose"
    assert current.created_at.tzinfo is not None


@pytest.mark.parametrize("cursor", ["!bad", "e30", "bnVsbA", "x" * 1025])
async def test_invalid_cursors_are_typed(archive: InvestigationArchive, cursor: str) -> None:
    with pytest.raises(HistoryError) as caught:
        await archive.list_owned("alice", cursor=cursor)
    assert caught.value.code == "history_cursor"


async def test_capacity_preserves_existing_archive_and_draft(archive: InvestigationArchive) -> None:
    assert isinstance(archive, MemoryInvestigations | SQLiteInvestigations)
    archive.limits = StorageLimits(investigations_per_actor=1, investigation_bytes=200, actor_bytes=400)
    identity = str(uuid4())
    await archive.create("alice", identity, "local", NOW)
    with pytest.raises(HistoryError) as caught:
        await archive.create("alice", str(uuid4()), "local", NOW)
    assert caught.value.code == "history_capacity"
    with pytest.raises(HistoryError) as caught:
        await archive.patch_workspace("alice", identity, WorkspacePatch(expected_revision=0, draft="я" * 100), NOW)
    assert caught.value.code == "history_capacity"
    assert (await archive.read("alice", identity)).workspace.draft == ""


async def test_create_enforces_actor_bytes_without_partial_state(archive: InvestigationArchive) -> None:
    """Two empty workspaces and their empty contexts require 176 UTF-8 bytes in total."""
    assert isinstance(archive, MemoryInvestigations | SQLiteInvestigations)
    archive.limits = StorageLimits(investigation_bytes=88, actor_bytes=175)
    existing, rejected = str(uuid4()), str(uuid4())
    initial = await archive.create("alice", existing, "local", NOW)
    preferences = await archive.patch_actor_workspace(
        "alice", ActorWorkspacePatch(expected_revision=0, last_investigation_id=existing, host="local"), NOW
    )
    with pytest.raises(HistoryError) as caught:
        await archive.create("alice", rejected, "local", NOW)
    assert caught.value.code == "history_capacity"
    assert (await archive.list_owned("alice")).items[0].id == existing
    assert len((await archive.list_owned("alice")).items) == 1
    assert await archive.read("alice", existing) == initial
    assert await archive.workspace("alice") == preferences
    with pytest.raises(HistoryError) as missing:
        await archive.read("alice", rejected)
    assert missing.value.code == "history_not_found"


@pytest.mark.parametrize(("investigation_bytes", "actor_bytes"), [(87, 1000), (1000, 87)])
async def test_create_rejects_oversized_initial_state(
    archive: InvestigationArchive, investigation_bytes: int, actor_bytes: int
) -> None:
    """The 86-byte workspace plus its two-byte model context must fit both byte quotas."""
    assert isinstance(archive, MemoryInvestigations | SQLiteInvestigations)
    archive.limits = StorageLimits(investigation_bytes=investigation_bytes, actor_bytes=actor_bytes)
    preferences = await archive.workspace("alice")
    identity = str(uuid4())
    with pytest.raises(HistoryError) as caught:
        await archive.create("alice", identity, "local", NOW)
    assert caught.value.code == "history_capacity"
    assert (await archive.list_owned("alice")).items == ()
    assert await archive.workspace("alice") == preferences
    with pytest.raises(HistoryError) as missing:
        await archive.read("alice", identity)
    assert missing.value.code == "history_not_found"


async def test_create_accepts_exact_byte_fit_and_returns_duplicates_before_quotas(
    archive: InvestigationArchive,
) -> None:
    assert isinstance(archive, MemoryInvestigations | SQLiteInvestigations)
    archive.limits = StorageLimits(investigation_bytes=88, actor_bytes=176)
    first, second = str(uuid4()), str(uuid4())
    initial = await archive.create("alice", first, "local", NOW)
    await archive.create("alice", second, "local", NOW)
    assert {item.id for item in (await archive.list_owned("alice")).items} == {first, second}
    archive.limits = StorageLimits(investigation_bytes=1, actor_bytes=1)
    assert await archive.create("alice", first, "local", NOW) == initial


async def test_running_archive_cannot_be_deleted(archive: InvestigationArchive) -> None:
    identity = str(uuid4())
    await archive.create("alice", identity, "local", NOW)
    snapshot = saved_turn(identity).model_copy(update={"state": "running"})
    await seed_turn(archive, snapshot)
    with pytest.raises(HistoryError) as caught:
        await archive.delete("alice", identity, NOW)
    assert caught.value.code == "turn_busy"
