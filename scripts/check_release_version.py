"""Check the shared DockSight release version in package metadata."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path


def main() -> int:
    """Report frontend version mismatches against the backend package version."""
    root = Path(__file__).resolve().parents[1]
    with (root / "backend/pyproject.toml").open("rb") as manifest:
        release_version: str = tomllib.load(manifest)["project"]["version"]

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
        f"{field} reports {version}."
        for field, version in versions.items()
        if version != release_version
    ]
    if mismatches:
        print(
            f"Expected DockSight release version {release_version} from backend/pyproject.toml.",
            file=sys.stderr,
        )
        print("\n".join(mismatches), file=sys.stderr)
        return 1

    print(f"Backend and frontend share DockSight release version {release_version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
