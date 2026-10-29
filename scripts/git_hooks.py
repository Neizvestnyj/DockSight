"""Install local Git guards and reject pushes targeting the protected branch."""

import argparse
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Final, TextIO

MARKER: Final = "# DockSight managed pre-push hook"
PROTECTED_REF: Final = "refs/heads/master"


class HookInstallationError(Exception):
    """Report an installation conflict without replacing another tool's hook."""


def validate_existing_hooks(directory: Path) -> None:
    """Prevent pre-commit migration from overwriting an existing legacy hook."""
    for name in ("pre-commit", "commit-msg"):
        hook = directory / name
        legacy = directory / f"{name}.legacy"
        if (hook.exists() or hook.is_symlink()) and (
            legacy.exists() or legacy.is_symlink()
        ):
            raise HookInstallationError(
                f"Existing {name} and {name}.legacy hooks were preserved; resolve the conflict before installing."
            )


def install_hooks() -> None:
    """Install pre-commit checks and a guard that reads every outgoing ref from Git."""
    resolved = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-path", "hooks/pre-push"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    hook = Path(resolved.stdout.strip())
    if (hook.exists() or hook.is_symlink()) and not hook.read_bytes().startswith(
        f"#!/bin/sh\n{MARKER}\n".encode()
    ):
        raise HookInstallationError(
            "Existing pre-push hook was preserved; integrate the branch guard before installing."
        )
    validate_existing_hooks(hook.parent)
    subprocess.run(
        [sys.executable, "-m", "pre_commit", "install"], check=True, timeout=30
    )
    interpreter = shlex.quote(Path(sys.executable).as_posix())
    script = shlex.quote(Path(__file__).resolve().as_posix())
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        f'#!/bin/sh\n{MARKER}\nexec {interpreter} {script} pre-push "$@"\n',
        encoding="utf-8",
        newline="\n",
    )
    hook.chmod(0o755)
    print("Installed pre-commit, commit-msg, and pre-push hooks.")


def check_push(updates: TextIO) -> int:
    """Reject any update or deletion of master, including multi-ref and explicit-refspec pushes."""
    for line in updates:
        fields = line.split()
        if len(fields) != 4:
            print("Cannot validate outgoing refs; push blocked.", file=sys.stderr)
            return 1
        if fields[2] == PROTECTED_REF:
            print(
                "Direct pushes to master are prohibited. Push a feature branch and open a pull request.",
                file=sys.stderr,
            )
            return 1
    return 0


def main() -> int:
    """Dispatch hook installation or Git's pre-push callback."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "pre-push"))
    parser.add_argument("remote", nargs="?")
    parser.add_argument("remote_url", nargs="?")
    arguments = parser.parse_args()
    if arguments.command == "pre-push":
        return check_push(sys.stdin)
    try:
        install_hooks()
    except (HookInstallationError, OSError, subprocess.SubprocessError) as error:
        print(f"Hook installation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
