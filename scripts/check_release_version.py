"""Check the shared DockSight release version in package metadata."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path


class ReleaseVersionError(ValueError):
    """Package metadata in a checkout disagrees about the release version."""


def release_version(root: Path) -> str:
    """Return the backend package version after verifying that frontend metadata matches it."""
    with (root / "backend/pyproject.toml").open("rb") as manifest:
        version: str = tomllib.load(manifest)["project"]["version"]

    frontend = root / "frontend"
    package = json.loads((frontend / "package.json").read_text(encoding="utf-8"))
    lockfile = json.loads((frontend / "package-lock.json").read_text(encoding="utf-8"))
    locked_package_version: str = lockfile["packages"][""]["version"]
    versions: dict[str, str] = {
        "frontend/package.json": package["version"],
        "frontend/package-lock.json version": lockfile["version"],
        'frontend/package-lock.json packages[""].version': locked_package_version,
    }
    mismatches = [
        f"{field} reports {found}."
        for field, found in versions.items()
        if found != version
    ]
    if mismatches:
        lines = [
            f"Expected DockSight release version {version} from backend/pyproject.toml.",
            *mismatches,
        ]
        raise ReleaseVersionError("\n".join(lines))
    return version


def main() -> int:
    """Report frontend version mismatches against the backend package version."""
    try:
        version = release_version(Path(__file__).resolve().parents[1])
    except ReleaseVersionError as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Backend and frontend share DockSight release version {version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
