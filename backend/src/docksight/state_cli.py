import argparse
import asyncio
import ctypes
import json
import os
import sys
from ctypes import wintypes
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from docksight.adapters.outbound.persistence.actions import SQLiteActions
from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.adapters.outbound.persistence.maintenance import StateMaintenance
from docksight.application.ports.state import ReconcileTarget
from docksight.domain.errors import DockSightError, ErrorKind


class _StatePath(BaseSettings):
    """Read only state ownership configuration for commands unrelated to runtime services."""

    model_config = SettingsConfigDict(env_prefix="DOCKSIGHT_", env_file=".env", extra="ignore")
    state_path: Path = Field(default=Path(".docksight/state.sqlite3"))


def _parser() -> argparse.ArgumentParser:
    """Require a command and expose separate offline preview and explicit confirmation inputs."""
    parser = argparse.ArgumentParser(description="Manage DockSight state with the backend stopped")
    parser.add_argument("--state-path", type=Path, default=None)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Inspect a disposable copy without recovering source state")
    backup = commands.add_parser("backup", help="Copy original main/journal bytes before opening SQLite")
    backup.add_argument("--destination", type=Path, required=True)
    commands.add_parser("migrate", help="Apply packaged forward migrations without startup recovery")
    reconcile = commands.add_parser("reconcile", help="Observe or explicitly reconcile one blocked target")
    reconcile.add_argument("--action-id", required=True)
    reconcile.add_argument("--expected-revision", type=int)
    reconcile.add_argument("--confirm-target")
    reconcile.add_argument("--actor")
    reconcile.add_argument("--reason")
    reconcile.add_argument("--acknowledge-unknown-outcome", action="store_true")
    return parser


def _confirming(arguments: argparse.Namespace) -> bool:
    """Distinguish read-only preview from a complete explicit operator confirmation."""
    values = [arguments.expected_revision, arguments.confirm_target, arguments.actor, arguments.reason]
    confirming = any(value is not None for value in values) or arguments.acknowledge_unknown_outcome
    if confirming and (any(value is None for value in values) or not arguments.acknowledge_unknown_outcome):
        raise DockSightError(
            "reconciliation_confirmation", "Reconciliation requires every explicit confirmation option"
        )
    return bool(confirming)


def _read_os_account() -> str:
    """Read the executing Windows thread account or POSIX effective-UID account directly from the OS."""
    if sys.platform == "win32":
        lookup = ctypes.WinDLL("advapi32", use_last_error=True).GetUserNameW
        lookup.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        lookup.restype = wintypes.BOOL
        size = wintypes.DWORD(257)
        account = ctypes.create_unicode_buffer(size.value)
        if not lookup(account, ctypes.byref(size)):
            raise ctypes.WinError()
        return account.value
    import pwd

    return pwd.getpwuid(os.geteuid()).pw_name


def _operator_identity() -> str:
    """Fail reconciliation safely when the executing OS account cannot be resolved for audit."""
    try:
        account = _read_os_account()
    except (OSError, KeyError) as error:
        raise DockSightError(
            "operator_identity_unavailable", "Executing OS account could not be resolved", ErrorKind.UNAVAILABLE
        ) from error
    if not account.strip() or len(account) > 256:
        raise DockSightError(
            "operator_identity_unavailable", "Executing OS account could not be resolved", ErrorKind.UNAVAILABLE
        )
    return account


async def _reconcile(database: PersistentDatabase, arguments: argparse.Namespace) -> str:
    """Construct only configured Docker reads and the offline reconciliation use case."""
    from docksight.adapters.outbound.docker.hosts import load_hosts
    from docksight.adapters.outbound.docker.runtime import DockerRuntime
    from docksight.application.action_reconciliation import ActionReconciliation
    from docksight.application.redaction import Redactor
    from docksight.bootstrap import Settings

    confirming = _confirming(arguments)
    settings = Settings()
    credentials = settings.api_credentials()
    secrets = tuple(credentials.values()) + tuple(
        secret.get_secret_value()
        for secret in (
            settings.model_api_key,
            settings.openai_api_key,
            settings.anthropic_api_key,
            settings.gemini_api_key,
            settings.compatible_api_key,
            settings.ollama_api_key,
        )
        if secret is not None
    )
    redactor = Redactor(secrets)
    runtime = DockerRuntime(load_hosts(settings.hosts_file), redactor, settings.env_allowlist, settings.docker_timeout)
    try:
        service = ActionReconciliation(runtime, SQLiteActions(database), tuple(credentials))
        if not confirming:
            return (await service.inspect(arguments.action_id)).model_dump_json()
        command = ReconcileTarget(
            action_id=arguments.action_id,
            expected_revision=arguments.expected_revision,
            confirm_target=arguments.confirm_target,
            actor=arguments.actor,
            operator=_operator_identity(),
            reason=redactor.text(arguments.reason),
            acknowledge_unknown_outcome=arguments.acknowledge_unknown_outcome,
        )
        return (await service.reconcile(command)).model_dump_json()
    finally:
        await runtime.close()


async def run_command(argv: list[str] | None = None) -> str:
    """Acquire the shared exclusive owner and run only the selected stopped-backend maintenance operation."""
    arguments = _parser().parse_args(argv)
    path = arguments.state_path if arguments.state_path is not None else _StatePath().state_path
    database = PersistentDatabase(path)
    mode: Literal["status", "backup", "migrate", "reconcile"] = arguments.command
    try:
        await database.open_existing(mode)
        if mode == "status":
            return json.dumps(asdict(await StateMaintenance(database).status()))
        if mode == "backup":
            copied = await StateMaintenance(database).backup(arguments.destination)
            return json.dumps({"copied": [str(item) for item in copied]})
        if mode == "migrate":
            await database.migrate()
            return json.dumps({"migrated": True})
        return await _reconcile(database, arguments)
    finally:
        await database.close()


def main() -> int:
    """Print safe maintenance output and return a nonzero status on configuration or storage failure."""
    try:
        print(asyncio.run(run_command()))
    except DockSightError as error:
        print(f"{error.code}: {error.message}", file=sys.stderr)
        return 1
    except ValidationError:
        print("configuration_invalid: Maintenance configuration or confirmation is invalid", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
