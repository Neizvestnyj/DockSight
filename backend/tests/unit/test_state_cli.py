import asyncio
import ctypes
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from docksight import state_cli
from docksight.adapters.outbound.persistence.actions import SQLiteActions
from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.adapters.outbound.persistence.rows import ActionAuditRow
from docksight.application.investigations.errors import StorageError
from docksight.domain.actions import ActionState, PreparedAction
from docksight.domain.errors import DockSightError
from tests.fakes import FakeRuntime


class OfflineRuntime(FakeRuntime):
    """Provide configured reads without constructing a live Docker connection."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Accept the composition arguments while preserving the complete runtime fake."""
        super().__init__()

    async def close(self) -> None:
        """Complete the CLI runtime lifecycle without mutating any target."""


def expected_os_operator() -> str:
    """Read the executing account independently of inherited identity environment variables."""
    if sys.platform == "win32":
        import win32api

        return win32api.GetUserName()
    import pwd

    return pwd.getpwuid(os.geteuid()).pw_name


async def test_status_and_backup_need_no_credentials_or_provider_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DOCKSIGHT_API_TOKEN", raising=False)
    monkeypatch.delenv("DOCKSIGHT_API_TOKENS", raising=False)
    monkeypatch.setenv("DOCKSIGHT_PROVIDER", "not-a-provider")
    source, backup = tmp_path / "state.sqlite3", tmp_path / "backup.sqlite3"
    database = PersistentDatabase(source)
    await database.initialize_server()
    await database.close()
    before = await asyncio.to_thread(source.read_bytes)
    result = json.loads(await state_cli.run_command(["--state-path", str(source), "status"]))
    assert result["schema_revision"] == "0001_state" and not result["recovery_required"]
    await state_cli.run_command(["--state-path", str(source), "backup", "--destination", str(backup)])
    assert await asyncio.to_thread(backup.read_bytes) == before
    assert await asyncio.to_thread(source.read_bytes) == before


@pytest.mark.parametrize("command", [["status"], ["migrate"], ["reconcile", "--action-id", "unknown"]])
async def test_maintenance_commands_fail_before_construction_when_backend_owns_lock(
    tmp_path: Path,
    command: list[str],
) -> None:
    database = PersistentDatabase(tmp_path / "state.sqlite3")
    await database.initialize_server()
    try:
        with pytest.raises(StorageError) as caught:
            await state_cli.run_command(["--state-path", str(database.path), *command])
        assert caught.value.code == "storage_locked"
    finally:
        await database.close()


async def test_cli_confirmation_audits_os_account_despite_poisoned_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from docksight.adapters.outbound.docker import runtime as docker

    actual_operator = expected_os_operator()
    poisoned = "review-injected-operator"
    for name in ("LOGNAME", "USER", "LNAME", "USERNAME"):
        monkeypatch.setenv(name, poisoned)
    monkeypatch.setenv("DOCKSIGHT_API_TOKEN", "a-configured-operator-token-12345")
    monkeypatch.setenv("DOCKSIGHT_PROVIDER", "ollama")
    monkeypatch.setattr(docker, "DockerRuntime", OfflineRuntime)
    database = PersistentDatabase(tmp_path / "state.sqlite3")
    await database.initialize_server()
    now = datetime.now(UTC)
    identity, abandoned = str(uuid4()), str(uuid4())
    store = SQLiteActions(database)
    for selected, container in [(identity, "a" * 64), (abandoned, "b" * 64)]:
        await store.add(
            PreparedAction(
                selected, "operator", "local", container, "restart", "fingerprint", now + timedelta(minutes=5)
            ),
            now,
        )
    claim = await store.claim(identity, "operator", "request-1", True, now)
    dispatch = await store.mark_dispatch(identity, claim.stored.revision, now)
    await store.complete(identity, dispatch.revision, ActionState.INDETERMINATE, "Unknown", now)
    await store.claim(abandoned, "operator", "request-2", True, now)
    await database.close()
    common = ["--state-path", str(database.path), "reconcile", "--action-id", identity]
    preview = json.loads(await state_cli.run_command(common))
    assert preview["blocked"] and preview["observation"]["exists"]
    with pytest.raises(DockSightError):
        await state_cli.run_command([*common, "--expected-revision", str(preview["revision"])])
    confirmed = json.loads(
        await state_cli.run_command(
            [
                *common,
                "--expected-revision",
                str(preview["revision"]),
                "--confirm-target",
                f"local/{'a' * 64}",
                "--actor",
                "operator",
                "--reason",
                "Verified settled a-configured-operator-token-12345",
                "--acknowledge-unknown-outcome",
            ]
        )
    )
    assert not confirmed["blocked"]
    assert poisoned not in json.dumps(confirmed)
    owner = PersistentDatabase(database.path)
    await owner.open_existing("reconcile")
    try:
        saved = await SQLiteActions(owner).get(abandoned, "operator", now)
        assert saved.phase == "claimed"
        fields = await owner.transaction(
            lambda session: session.scalar(
                select(ActionAuditRow.fields).where(ActionAuditRow.event == "action.reconciled")
            )
        )
        assert fields is not None
        assert "a-configured-operator-token-12345" not in fields
        assert json.loads(fields)["operator"] == actual_operator
        assert poisoned not in fields
        actor = await owner.transaction(
            lambda session: session.scalar(
                select(ActionAuditRow.actor).where(ActionAuditRow.event == "action.reconciled")
            )
        )
        assert actor == "operator"
    finally:
        await owner.close()


async def test_unavailable_os_identity_preserves_block_and_authoritative_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from docksight.adapters.outbound.docker import runtime as docker

    def unavailable(*args: object, **kwargs: object) -> str:
        """Simulate an unavailable OS identity API without inventing an environment fallback."""
        raise OSError("Identity API unavailable")

    monkeypatch.setenv("DOCKSIGHT_API_TOKEN", "a-configured-operator-token-12345")
    monkeypatch.setenv("DOCKSIGHT_PROVIDER", "ollama")
    for name in ("LOGNAME", "USER", "LNAME", "USERNAME"):
        monkeypatch.setenv(name, "review-injected-operator")
    monkeypatch.setattr(docker, "DockerRuntime", OfflineRuntime)
    if sys.platform == "win32":
        monkeypatch.setattr(ctypes, "WinDLL", unavailable)
    else:
        import pwd

        monkeypatch.setattr(pwd, "getpwuid", unavailable)
    database = PersistentDatabase(tmp_path / "state.sqlite3")
    await database.initialize_server()
    now = datetime.now(UTC)
    identity = str(uuid4())
    store = SQLiteActions(database)
    try:
        await store.add(
            PreparedAction(
                identity, "operator", "local", "a" * 64, "restart", "fingerprint", now + timedelta(minutes=5)
            ),
            now,
        )
        claimed = await store.claim(identity, "operator", "request-1", True, now)
        dispatched = await store.mark_dispatch(identity, claimed.stored.revision, now)
        await store.complete(identity, dispatched.revision, ActionState.INDETERMINATE, "Unknown", now)
        before = await store.inspect_block(identity)
        events_before = await database.transaction(lambda session: list(session.scalars(select(ActionAuditRow.event))))
    finally:
        await database.close()
    with pytest.raises(DockSightError) as caught:
        await state_cli.run_command(
            [
                "--state-path",
                str(database.path),
                "reconcile",
                "--action-id",
                identity,
                "--expected-revision",
                str(before.revision),
                "--confirm-target",
                f"local/{'a' * 64}",
                "--actor",
                "operator",
                "--reason",
                "Verified old operation settled",
                "--acknowledge-unknown-outcome",
            ]
        )
    assert caught.value.code == "operator_identity_unavailable"
    assert "review-injected-operator" not in caught.value.message
    owner = PersistentDatabase(database.path)
    await owner.open_existing("reconcile")
    try:
        assert await SQLiteActions(owner).inspect_block(identity) == before
        assert (
            await owner.transaction(lambda session: list(session.scalars(select(ActionAuditRow.event))))
            == events_before
        )
    finally:
        await owner.close()
