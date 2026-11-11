import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from docksight.adapters.outbound.persistence.actions import SQLiteActions
from docksight.adapters.outbound.persistence.browser_sessions import SQLiteBrowserSessions
from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.adapters.outbound.persistence.investigations import SQLiteInvestigations
from docksight.adapters.outbound.persistence.turns import SQLiteTurnStore
from docksight.application.browser_sessions import BrowserSessions
from docksight.application.investigations.contracts import QuestionTurn, StartTurn
from docksight.application.investigations.errors import StorageError
from docksight.application.ports.browser_sessions import BrowserSession
from docksight.application.ports.models import ModelReply
from docksight.bootstrap import Settings, build_components
from docksight.domain.actions import PreparedAction
from docksight.domain.errors import DockSightError
from docksight.main import create_app
from tests.fakes import FakeRuntime, ScriptedModel


def test_server_initializes_lock_migration_and_recovery_before_readiness(tmp_path: Path) -> None:
    events: list[str] = []
    original_acquire = PersistentDatabase._acquire
    original_upgrade = PersistentDatabase._upgrade
    original_recover = PersistentDatabase._recover
    settings = Settings(
        api_token="startup-token-at-least-24-characters", state_path=tmp_path / "state.sqlite3", _env_file=None
    )
    runtime, model = FakeRuntime(), ScriptedModel([])
    components = build_components(settings, reader=runtime, writer=runtime, model=model)
    assert not components.ready and not settings.state_path.exists()

    def acquire(database: PersistentDatabase, *, create: bool) -> None:
        """Record actual lock acquisition without replacing its filesystem behavior."""
        assert not components.ready
        events.append("lock")
        original_acquire(database, create=create)

    def upgrade(database: PersistentDatabase) -> None:
        """Run actual packaged migrations only after process ownership exists."""
        assert events == ["lock"] and not components.ready
        events.append("migration")
        original_upgrade(database)

    def recover(database: PersistentDatabase, session):
        """Run all registered callbacks in the database's real atomic recovery transaction."""
        assert events == ["lock", "migration"] and not components.ready
        events.append("recovery")
        assert len(database.recoveries) == 3
        return original_recover(database, session)

    with (
        patch.object(PersistentDatabase, "_acquire", acquire),
        patch.object(PersistentDatabase, "_upgrade", upgrade),
        patch.object(PersistentDatabase, "_recover", recover),
        TestClient(create_app(settings, components)) as api,
    ):
        assert events == ["lock", "migration", "recovery"]
        assert components.ready and api.get("/health/ready").status_code == 200
        assert model.requests == [] and runtime.mutations == []
    assert not components.ready


async def test_startup_lock_failure_never_falls_back_to_memory(tmp_path: Path) -> None:
    settings = Settings(
        api_token="startup-token-at-least-24-characters", state_path=tmp_path / "state.sqlite3", _env_file=None
    )
    runtime = FakeRuntime()
    first = build_components(settings, reader=runtime, writer=runtime, model=ScriptedModel([]))
    second = build_components(settings, reader=runtime, writer=runtime, model=ScriptedModel([]))
    try:
        await first.start()
        with pytest.raises(StorageError) as locked:
            await second.start()
        assert locked.value.code == "storage_locked" and not second.ready
        assert second.database is not None
    finally:
        await second.close()
        await first.close()


async def test_explicit_memory_mode_enforces_legacy_session_capacity_and_idle_lifetime() -> None:
    now = datetime.now(UTC)
    settings = Settings(
        api_token="startup-token-at-least-24-characters",
        state_backend="memory",
        max_sessions=1,
        state_ttl=60,
        _env_file=None,
    )
    runtime = FakeRuntime()
    components = build_components(settings, reader=runtime, writer=runtime, model=ScriptedModel([]))
    try:
        await components.start()
        first, second = str(uuid4()), str(uuid4())
        await components.investigations.create("operator", first, "local")
        with pytest.raises(DockSightError) as full:
            await components.investigations.create("operator", second, "local")
        assert full.value.code == "session_capacity"
        with patch("docksight.adapters.outbound.memory.transient.datetime") as clock:
            clock.now.return_value = now + timedelta(seconds=61)
            created = await components.investigations.create("operator", second, "local")
        assert created.id == second
        with pytest.raises(DockSightError):
            await components.investigations.read("operator", first)
        assert components.database is None
    finally:
        await components.close()


async def test_startup_recovers_turns_actions_and_obsolete_sessions_atomically(tmp_path: Path) -> None:
    now, identity = datetime.now(UTC), str(uuid4())
    path = tmp_path / "state.sqlite3"
    seed = PersistentDatabase(path)
    await seed.initialize_server()
    archive, turns = SQLiteInvestigations(seed), SQLiteTurnStore(seed)
    await archive.create("operator", identity, "local", now)
    command = StartTurn(
        QuestionTurn(investigation_id=identity, submission_id=str(uuid4()), expected_revision=0, query="Inspect")
    )
    saved = (await turns.accept("operator", command, "a" * 64, "original-request", now)).snapshot
    action_id = str(uuid4())
    actions = SQLiteActions(seed)
    await actions.add(
        PreparedAction(action_id, "operator", "local", "a" * 64, "restart", "fingerprint", now + timedelta(minutes=5)),
        now,
    )
    await actions.claim(action_id, "operator", "original-key", True, now)
    await actions.mark_dispatch(action_id, 1, now)
    sessions = SQLiteBrowserSessions(seed)
    obsolete = await BrowserSessions(sessions).login("operator", "b" * 64)
    for index in range(105):
        await sessions.add(
            BrowserSession(
                token_hash=f"{index:064x}",
                actor="operator",
                credential_fingerprint="b" * 64,
                created_at=now - timedelta(hours=2),
                last_seen_at=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
            )
        )
    await seed.close()
    runtime, model = FakeRuntime(), ScriptedModel([])
    settings = Settings(api_token="startup-token-at-least-24-characters", state_path=path, _env_file=None)
    components = build_components(settings, reader=runtime, writer=runtime, model=model)
    try:
        await components.start()
        retained = await components.investigations.archive.read_turn("operator", saved.id)
        assert retained.state == "interrupted" and retained.request_id == "original-request"
        assert (await components.investigations.read("operator", identity)).active_turn_id is None
        assert (await components.actions.get(action_id, "operator")).state == "indeterminate"
        assert components.database is not None
        protected = await SQLiteActions(components.database).inspect_block(action_id)
        assert protected.blocked and protected.unresolved_actions == (action_id,)
        remaining = await components.browser_sessions.cleanup(limit=100)
        assert remaining == 6
        assert await components.browser_sessions.cleanup(limit=100) == 0
        assert await components.browser_sessions.store.get(hashlib.sha256(obsolete.cookie.encode()).hexdigest()) is None
        assert model.requests == [] and runtime.mutations == []
    finally:
        await components.close()


async def test_shutdown_interrupts_retained_generation_before_closing_adapter_owners(tmp_path: Path) -> None:
    events: list[str] = []
    entered = asyncio.Event()

    class PendingModel(ScriptedModel):
        """Leave actual diagnostics in a model call until lifespan interruption settles it."""

        async def complete(self, messages, tools=(), schema=None) -> ModelReply:
            """Record cleanup of the cancelled external boundary before any owner closes."""
            entered.set()
            try:
                await asyncio.Event().wait()
                raise AssertionError("Unreachable model completion")
            finally:
                events.append("diagnostic")

    settings = Settings(
        api_token="startup-token-at-least-24-characters", state_path=tmp_path / "state.sqlite3", _env_file=None
    )
    runtime = FakeRuntime()
    components = build_components(settings, reader=runtime, writer=runtime, model=PendingModel([]))
    await components.start()
    identity = str(uuid4())
    await components.investigations.create("operator", identity, "local")
    command = StartTurn(
        QuestionTurn(investigation_id=identity, submission_id=str(uuid4()), expected_revision=0, query="Inspect")
    )
    saved = (await components.runner.submit("operator", command, "original-request")).snapshot
    await asyncio.wait_for(entered.wait(), 2)
    components.runner.shutdown_timeout = 0
    assert components.database is not None
    original_close = components.database.close
    original_actions_close = components.actions.close

    async def close_database() -> None:
        """Read the settled terminal revision while SQLite is still owned and available."""
        assert events == ["diagnostic", "actions", "provider", "runtime"]
        retained = await components.investigations.archive.read_turn("operator", saved.id)
        assert retained.state == "interrupted"
        events.append("database")
        await original_close()

    async def close_actions() -> None:
        """Drain action admissions before closing external adapters."""
        await original_actions_close()
        events.append("actions")

    async def close_runtime() -> None:
        """Record the injected runtime owner's shutdown position."""
        events.append("runtime")

    async def close_provider() -> None:
        """Record that generation has settled before its provider owner closes."""
        assert events[0] == "diagnostic"
        events.append("provider")

    components.actions.close = close_actions
    components.closers[:] = [close_database, close_runtime, close_provider]
    await components.close()
    assert events == ["diagnostic", "actions", "provider", "runtime", "database"]
    assert not components.ready
