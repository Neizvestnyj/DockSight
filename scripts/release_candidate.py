"""Qualify a CI-tested DockSight commit on master for release publication."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast
from urllib.parse import quote, urlparse

from check_release_version import ReleaseVersionError, release_version

BRANCH: Final[str] = "master"
REQUIRED_WORKFLOWS: Final[Mapping[str, str]] = {
    "Backend": "backend.yml",
    "Frontend": "frontend.yml",
    "Secret scanning": "secret-scan.yml",
}
FIRST_RELEASE: Final[tuple[int, int, int]] = (1, 0, 0)
SHA_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}")
VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
)
API_TIMEOUT: Final[int] = 30
DEFAULT_API_URL: Final[str] = "https://api.github.com"
UPLOADS_HOST: Final[str] = "uploads.github.com"

type Api = Callable[[str], object | None]


class QualificationError(Exception):
    """Release metadata, API responses, or repository state forbid publishing this candidate."""


@dataclass(frozen=True)
class Decision:
    """Outcome of qualifying one workflow completion."""

    qualified: bool
    publish: bool
    reason: str
    sha: str = ""
    version: str = ""
    notes: str = ""

    @property
    def tag(self) -> str:
        """Return the Git and OCI tag for a resolved version."""
        return f"v{self.version}" if self.version else ""


class GitHubApi:
    """Read GitHub REST resources with a short-lived job token."""

    def __init__(self, base_url: str, token: str) -> None:
        """Bind the API origin and bearer token."""
        if not base_url.startswith(("https://", "http://127.0.0.1:")):
            raise QualificationError("GitHub API URL must use HTTPS")
        self.base_url = base_url.rstrip("/")
        self.token = token

    def __call__(self, path: str) -> object | None:
        """Return decoded JSON, None for 404, and raise for every other failure."""
        try:
            return self._open(
                self._request("GET", path, None, "application/json"), path
            )
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise QualificationError(
                f"GitHub API returned HTTP {error.code} for {path}"
            ) from error

    def send(
        self,
        method: str,
        path: str,
        payload: object | None = None,
        data: bytes | None = None,
        content_type: str = "application/json",
    ) -> object | None:
        """Write a JSON payload or raw bytes and return the decoded response, raising on any HTTP error."""
        body = (
            data
            if data is not None
            else None
            if payload is None
            else json.dumps(payload).encode()
        )
        try:
            return self._open(self._request(method, path, body, content_type), path)
        except urllib.error.HTTPError as error:
            raise QualificationError(
                f"GitHub API returned HTTP {error.code} for {method} {path}"
            ) from error

    def _request(
        self, method: str, path: str, body: bytes | None, content_type: str
    ) -> urllib.request.Request:
        """Build an authenticated request for the API origin or GitHub's upload origin."""
        url = path if path.startswith("https://") else self.base_url + path
        if urlparse(url).netloc not in {urlparse(self.base_url).netloc, UPLOADS_HOST}:
            raise QualificationError(
                f"Refusing GitHub request to an unexpected host: {url}"
            )
        return urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": content_type,
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "docksight-release",
            },
        )

    @staticmethod
    def _open(request: urllib.request.Request, path: str) -> object | None:
        """Send a request and decode a JSON body, returning None for an empty body."""
        try:
            with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
                raw: bytes = response.read()
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError) as error:
            raise QualificationError(f"GitHub API request failed for {path}") from error
        try:
            data: object = json.loads(raw.decode("utf-8")) if raw else None
        except ValueError as error:
            raise QualificationError(
                f"GitHub API returned invalid JSON for {path}"
            ) from error
        return data


def field(value: object, *path: str) -> object:
    """Read a nested JSON object member and reject unexpected shapes."""
    current = value
    for key in path:
        if not isinstance(current, dict) or key not in current:
            raise QualificationError(f"GitHub response lacks {'.'.join(path)}")
        current = cast(dict[str, object], current)[key]
    return current


def text(value: object, *path: str) -> str:
    """Read a nested JSON string member."""
    member = field(value, *path)
    if not isinstance(member, str):
        raise QualificationError(
            f"GitHub response field {'.'.join(path)} is not a string"
        )
    return member


def items(value: object, *path: str) -> list[object]:
    """Read a nested JSON array member."""
    member = field(value, *path) if path else value
    if not isinstance(member, list):
        raise QualificationError(
            f"GitHub response field {'.'.join(path) or 'body'} is not a list"
        )
    return cast(list[object], member)


def required(api: Api, path: str) -> object:
    """Read a resource that must exist."""
    data = api(path)
    if data is None:
        raise QualificationError(f"GitHub returned 404 for {path}")
    return data


def candidate_sha(event: object, repository: str) -> str | None:
    """Return the commit of a successful same-repository master push completion, or None."""
    run = field(event, "workflow_run")
    sha = text(run, "head_sha")
    eligible = (
        field(event, "action") == "completed"
        and field(run, "name") in REQUIRED_WORKFLOWS
        and field(run, "conclusion") == "success"
        and is_master_push(run, repository, sha)
        and SHA_PATTERN.fullmatch(sha) is not None
    )
    return sha if eligible else None


def is_master_push(run: object, repository: str, sha: str) -> bool:
    """Check that a workflow run tested this commit for a same-repository push to master."""
    return (
        field(run, "head_sha") == sha
        and field(run, "event") == "push"
        and field(run, "head_branch") == BRANCH
        and field(run, "head_repository", "full_name") == repository
    )


def run_order(run: object) -> tuple[int, int]:
    """Order runs and reruns so the latest attempt wins."""
    number, attempt = field(run, "run_number"), field(run, "run_attempt")
    if not isinstance(number, int) or not isinstance(attempt, int):
        raise QualificationError(
            "GitHub workflow run lacks numeric run_number or run_attempt"
        )
    return number, attempt


def latest_run(api: Api, repository: str, workflow: str, sha: str) -> object | None:
    """Return the latest attempt of a workflow for a master push of this commit."""
    path = (
        f"/repos/{repository}/actions/workflows/{workflow}/runs"
        f"?head_sha={sha}&branch={BRANCH}&event=push&per_page=100"
    )
    runs = [
        run
        for run in items(required(api, path), "workflow_runs")
        if is_master_push(run, repository, sha)
    ]
    return max(runs, key=run_order, default=None)


def unfinished_checks(api: Api, repository: str, sha: str) -> list[str]:
    """Name required workflows whose latest run for this commit has not succeeded."""
    unfinished: list[str] = []
    for name, workflow in REQUIRED_WORKFLOWS.items():
        run = latest_run(api, repository, workflow, sha)
        if (
            run is None
            or field(run, "status") != "completed"
            or field(run, "conclusion") != "success"
        ):
            unfinished.append(name)
    return unfinished


def on_branch(api: Api, repository: str, sha: str) -> bool:
    """Check that the commit is an ancestor of the current master head."""
    comparison = required(api, f"/repos/{repository}/compare/{sha}...{BRANCH}")
    return field(comparison, "status") in {"ahead", "identical"}


def parse_version(version: str) -> tuple[int, int, int]:
    """Parse a strict X.Y.Z release version."""
    match = VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise QualificationError(f"Version {version!r} is not X.Y.Z")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def backend_version(root: Path) -> str:
    """Read the backend package version from a checkout."""
    with (root / "backend/pyproject.toml").open("rb") as manifest:
        version = tomllib.load(manifest).get("project", {}).get("version")
    if not isinstance(version, str):
        raise QualificationError("backend/pyproject.toml has no project version")
    return version


def changelog_notes(changelog: str, version: str) -> str:
    """Return the body of the exact changelog section for a version."""
    heading = re.compile(
        rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", re.MULTILINE
    )
    match = heading.search(changelog)
    if match is None:
        raise QualificationError(
            f"CHANGELOG.md has no '## [{version}] - YYYY-MM-DD' section"
        )
    rest = changelog[match.end() :]
    end = re.search(r"^## |^\[[^\]]+\]: ", rest, re.MULTILINE)
    notes = rest[: end.start() if end else len(rest)].strip()
    if not notes:
        raise QualificationError(f"CHANGELOG.md section {version} is empty")
    return notes + "\n"


def tag_commit(api: Api, repository: str, tag: str) -> str | None:
    """Resolve a Git tag to its commit, following an annotated tag object."""
    ref = api(f"/repos/{repository}/git/ref/tags/{quote(tag)}")
    if ref is None:
        return None
    sha = text(ref, "object", "sha")
    if field(ref, "object", "type") == "tag":
        sha = text(
            required(api, f"/repos/{repository}/git/tags/{sha}"), "object", "sha"
        )
    return sha


def publication_state(api: Api, repository: str, tag: str, sha: str) -> str:
    """Return 'published' to skip or 'pending' to publish, and fail on another candidate's tag or draft."""
    release = api(f"/repos/{repository}/releases/tags/{quote(tag)}")
    if release is not None and field(release, "draft") is False:
        return "published"
    commit = tag_commit(api, repository, tag)
    if commit is not None and commit != sha:
        raise QualificationError(f"Tag {tag} points at {commit}, not candidate {sha}")
    check_drafts(api, repository, tag, sha)
    return "pending"


def check_drafts(api: Api, repository: str, tag: str, sha: str) -> None:
    """Fail when a draft for the tag targets another commit; drafts are visible only to write tokens."""
    for draft in items(required(api, f"/repos/{repository}/releases?per_page=100")):
        if field(draft, "draft") is not True or field(draft, "tag_name") != tag:
            continue
        target = text(draft, "target_commitish")
        if target != sha:
            raise QualificationError(
                f"Draft release {tag} targets {target}, not candidate {sha}"
            )


def release_decision(api: Api, repository: str, root: Path, sha: str) -> Decision:
    """Validate release metadata of a qualified commit and decide whether to publish it."""
    version = backend_version(root)
    if parse_version(version) < FIRST_RELEASE:
        return Decision(
            True,
            False,
            f"Version {version} is below 1.0.0; publication skipped",
            sha,
            version,
        )
    try:
        release_version(root)
    except ReleaseVersionError as error:
        raise QualificationError(str(error)) from error
    notes = changelog_notes(
        (root / "CHANGELOG.md").read_text(encoding="utf-8"), version
    )
    tag = f"v{version}"
    if publication_state(api, repository, tag, sha) == "published":
        return Decision(True, False, f"{tag} is already published", sha, version)
    return Decision(True, True, f"{tag} qualified from {sha}", sha, version, notes)


def qualify(event: object, repository: str, root: Path, api: Api) -> Decision:
    """Qualify the commit of a workflow completion once all required checks passed on it."""
    sha = candidate_sha(event, repository)
    if sha is None:
        return Decision(
            False, False, "Event is not a successful same-repository push to master"
        )
    unfinished = unfinished_checks(api, repository, sha)
    if unfinished:
        return Decision(
            False,
            False,
            f"Waiting for successful {', '.join(unfinished)} runs on {sha}",
            sha,
        )
    if not on_branch(api, repository, sha):
        return Decision(
            False, False, f"{sha} is not in the current {BRANCH} history", sha
        )
    return release_decision(api, repository, root, sha)


def write_outputs(values: Mapping[str, str]) -> None:
    """Append single-line step outputs to GITHUB_OUTPUT, or print them locally."""
    if any("\n" in value or "\r" in value for value in values.values()):
        raise QualificationError("Step outputs must be single-line")
    lines = "".join(f"{key}={value}\n" for key, value in values.items())
    destination = os.environ.get("GITHUB_OUTPUT")
    if destination:
        with Path(destination).open("a", encoding="utf-8", newline="\n") as output:
            output.write(lines)
    else:
        sys.stdout.write(lines)


def github_api() -> GitHubApi:
    """Create an API client from the job environment."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise QualificationError("GITHUB_TOKEN is required")
    return GitHubApi(os.environ.get("GITHUB_API_URL", DEFAULT_API_URL), token)


def run_qualify(arguments: argparse.Namespace) -> None:
    """Qualify the triggering completion and write outputs and release notes."""
    event: object = json.loads(Path(arguments.event).read_text(encoding="utf-8"))
    decision = qualify(event, arguments.repository, Path(arguments.root), github_api())
    Path(arguments.notes).write_text(decision.notes, encoding="utf-8", newline="\n")
    print(decision.reason)
    write_outputs(
        {
            "qualified": str(decision.qualified).lower(),
            "publish": str(decision.publish).lower(),
            "sha": decision.sha,
            "version": decision.version,
            "tag": decision.tag,
        }
    )


def run_state(arguments: argparse.Namespace) -> None:
    """Recheck release state for a candidate under the publication lock."""
    if SHA_PATTERN.fullmatch(arguments.sha) is None:
        raise QualificationError("--sha must be a full commit SHA")
    state = publication_state(
        github_api(), arguments.repository, arguments.tag, arguments.sha
    )
    print(f"{arguments.tag} is {state}")
    write_outputs({"state": state})


def main(argv: Sequence[str] | None = None) -> int:
    """Run the qualify or state command."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    qualify_command = commands.add_parser(
        "qualify", help="Qualify a workflow_run completion"
    )
    qualify_command.add_argument(
        "--event", required=True, help="workflow_run event JSON"
    )
    qualify_command.add_argument("--repository", required=True, help="owner/name")
    qualify_command.add_argument(
        "--root", required=True, help="Checkout of the candidate commit"
    )
    qualify_command.add_argument(
        "--notes", required=True, help="Release notes destination"
    )
    qualify_command.set_defaults(handler=run_qualify)
    state_command = commands.add_parser(
        "state", help="Recheck release state for a candidate"
    )
    state_command.add_argument("--repository", required=True, help="owner/name")
    state_command.add_argument("--sha", required=True, help="Candidate commit")
    state_command.add_argument("--tag", required=True, help="Release tag")
    state_command.set_defaults(handler=run_state)
    arguments = parser.parse_args(argv)
    try:
        arguments.handler(arguments)
    except QualificationError as error:
        print(f"Release qualification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
