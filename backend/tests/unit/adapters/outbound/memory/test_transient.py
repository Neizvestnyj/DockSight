from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest

from docksight.adapters.outbound.memory.transient import TransientInvestigations
from docksight.adapters.outbound.memory.turns import MemoryTurnStore
from docksight.application.investigations.contracts import QuestionTurn, StartTurn, TurnOutcome
from docksight.domain.errors import DockSightError


async def test_memory_idle_expiry_removes_content_and_retains_deleted_receipts() -> None:
    now, identity = datetime.now(UTC), str(uuid4())
    archive = TransientInvestigations(capacity=1, ttl=60)
    turns = MemoryTurnStore(archive)
    await archive.create("alice", identity, "local", now)
    command = StartTurn(
        QuestionTurn(investigation_id=identity, submission_id=str(uuid4()), expected_revision=0, query="Inspect")
    )
    saved = (await turns.accept("alice", command, "a" * 64, "request", now)).snapshot
    await turns.finish("alice", saved.id, TurnOutcome(expected_revision=0, state="stopped"), now)
    with patch("docksight.adapters.outbound.memory.transient.datetime") as clock:
        clock.now.return_value = now + timedelta(seconds=60)
        assert (await archive.list_owned("alice")).items == ()
        assert (await archive.workspace("alice")).last_investigation_id is None
        with pytest.raises(DockSightError) as gone:
            await turns.submission("alice", command.root.submission_id, "a" * 64)
        assert gone.value.code == "history_deleted"
        with pytest.raises(DockSightError):
            await archive.read_turn("alice", saved.id)
        with pytest.raises(DockSightError):
            await archive.turns("alice", identity)


async def test_memory_idle_expiry_never_evicts_an_active_diagnostic() -> None:
    now, identity = datetime.now(UTC), str(uuid4())
    archive = TransientInvestigations(capacity=1, ttl=60)
    turns = MemoryTurnStore(archive)
    await archive.create("alice", identity, "local", now)
    command = StartTurn(
        QuestionTurn(investigation_id=identity, submission_id=str(uuid4()), expected_revision=0, query="Inspect")
    )
    saved = (await turns.accept("alice", command, "a" * 64, "request", now)).snapshot
    with patch("docksight.adapters.outbound.memory.transient.datetime") as clock:
        clock.now.return_value = now + timedelta(seconds=61)
        assert (await archive.read("alice", identity)).active_turn_id == saved.id
        assert (await archive.read_turn("alice", saved.id)).state == "running"
        with pytest.raises(DockSightError) as full:
            await archive.create("bob", str(uuid4()), "local", now + timedelta(seconds=61))
        assert full.value.code == "session_capacity"


async def test_memory_search_matches_owned_question_and_preserves_pagination() -> None:
    now, identity, older = datetime.now(UTC), str(uuid4()), str(uuid4())
    archive = TransientInvestigations(capacity=4, ttl=60)
    turns = MemoryTurnStore(archive)
    await archive.create("alice", older, "strasse", now - timedelta(seconds=1))
    await archive.create("alice", identity, "local", now)
    await archive.create("bob", str(uuid4()), "strasse", now)
    command = StartTurn(
        QuestionTurn(investigation_id=identity, submission_id=str(uuid4()), expected_revision=0, query="Straße?")
    )
    saved = (await turns.accept("alice", command, "a" * 64, "request", now)).snapshot
    first = await archive.search("alice", "strasse", limit=1)
    assert [item.id for item in first.items] == [identity]
    match = first.items[0].match
    assert match is not None
    assert (match.turn_id, match.excerpt, match.start, match.end) == (saved.id, "Straße?", 0, 6)
    assert first.next_cursor is not None
    second = await archive.search("alice", "strasse", cursor=first.next_cursor)
    assert [item.id for item in second.items] == [older]
    assert second.items[0].match is None and second.next_cursor is None
    assert (await archive.search("alice", "%")).items == ()
    with patch("docksight.adapters.outbound.memory.transient.datetime") as clock:
        clock.now.return_value = now + timedelta(seconds=60)
        assert [item.id for item in (await archive.search("alice", "strasse")).items] == [identity]
