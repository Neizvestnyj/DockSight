"""Qualify release candidates from GitHub workflow events and API responses without network access."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[3]
REPOSITORY: Final = "Neizvestnyj/DockSight"
SHA: Final = "a" * 40
OTHER_SHA: Final = "b" * 40
WORKFLOWS: Final = {"Backend": "backend.yml", "Frontend": "frontend.yml", "Secret scanning": "secret-scan.yml"}


def _load() -> ModuleType:
    """Import the release candidate script with its sibling version checker."""
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("release_candidate", ROOT / "scripts/release_candidate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


candidate = _load()


def _run(name: str = "Backend", **overrides: Any) -> dict[str, Any]:
    """Build a workflow run payload for a successful same-repository push to master."""
    run: dict[str, Any] = {
        "name": name,
        "head_sha": SHA,
        "head_branch": "master",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "run_number": 7,
        "run_attempt": 1,
        "head_repository": {"full_name": REPOSITORY},
    }
    run.update(overrides)
    return run


def _event(**overrides: Any) -> dict[str, Any]:
    """Build a workflow_run completion event."""
    return {"action": "completed", "workflow_run": _run(**overrides)}


class FakeApi:
    """Serve canned GitHub API responses by request path and record each read."""

    def __init__(self, routes: dict[str, object]) -> None:
        """Keep responses; a missing route is a 404."""
        self.routes = routes
        self.paths: list[str] = []

    def __call__(self, path: str) -> object | None:
        """Return the canned response, or raise a canned exception."""
        self.paths.append(path)
        response = self.routes.get(path)
        if isinstance(response, Exception):
            raise response
        return response


def _runs_path(workflow: str, sha: str = SHA) -> str:
    """Return the filtered workflow-runs path the policy must query."""
    return f"/repos/{REPOSITORY}/actions/workflows/{workflow}/runs?head_sha={sha}&branch=master&event=push&per_page=100"


def _routes(**changes: object) -> dict[str, object]:
    """Build API state where all checks passed on master and nothing is published yet."""
    routes: dict[str, object] = {
        _runs_path(workflow): {"workflow_runs": [_run(name)]} for name, workflow in WORKFLOWS.items()
    }
    routes[f"/repos/{REPOSITORY}/compare/{SHA}...master"] = {"status": "ahead"}
    routes[f"/repos/{REPOSITORY}/releases?per_page=100"] = []
    routes.update(changes)
    return routes


def _checkout(
    tmp_path: Path, version: str = "1.0.0", changelog: str | None = None, frontend: str | None = None
) -> Path:
    """Write the release metadata files of a candidate checkout."""
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend/pyproject.toml").write_text(f'[project]\nname = "docksight"\nversion = "{version}"\n')
    package_version = frontend or version
    (tmp_path / "frontend/package.json").write_text(json.dumps({"version": package_version}))
    lockfile = {"version": package_version, "packages": {"": {"version": package_version}}}
    (tmp_path / "frontend/package-lock.json").write_text(json.dumps(lockfile))
    text = (
        changelog
        if changelog is not None
        else (
            f"# Changelog\n\n## [{version}] - 2026-11-24\n\n### Added\n\n- Install with Docker Compose — “quoted”.\n\n"
            "## [0.9.2] - 2026-11-23\n\n### Fixed\n\n- Older.\n\n"
            f"[{version}]: https://example.invalid/compare\n"
        )
    )
    (tmp_path / "CHANGELOG.md").write_text(text, encoding="utf-8")
    return tmp_path


def test_three_successful_workflows_on_one_master_sha_qualify_with_changelog_notes(tmp_path: Path) -> None:
    decision = candidate.qualify(_event(), REPOSITORY, _checkout(tmp_path), FakeApi(_routes()))

    assert (decision.qualified, decision.publish) == (True, True)
    assert (decision.sha, decision.version, decision.tag) == (SHA, "1.0.0", "v1.0.0")
    assert decision.notes == "### Added\n\n- Install with Docker Compose — “quoted”.\n"


@pytest.mark.parametrize(
    "event",
    [
        _event(head_repository={"full_name": "someone/DockSight"}),
        _event(event="pull_request"),
        _event(event="workflow_dispatch"),
        _event(head_branch="feature/release-ci"),
        _event(conclusion="failure"),
        _event(name="Publish coverage badge data"),
        _event(head_sha="not-a-sha"),
        {"action": "requested", "workflow_run": _run()},
    ],
    ids=["fork", "pull-request", "dispatch", "branch", "failed", "unknown-workflow", "bad-sha", "not-completed"],
)
def test_ineligible_events_do_not_qualify_or_query_the_api(tmp_path: Path, event: dict[str, Any]) -> None:
    api = FakeApi(_routes())
    decision = candidate.qualify(event, REPOSITORY, _checkout(tmp_path), api)

    assert (decision.qualified, decision.publish) == (False, False)
    assert api.paths == []


@pytest.mark.parametrize(
    "run",
    [
        _run("Frontend", head_sha=OTHER_SHA),
        _run("Frontend", head_repository={"full_name": "someone/DockSight"}),
        _run("Frontend", event="pull_request"),
        _run("Frontend", head_branch="feature/release-ci"),
        _run("Frontend", conclusion="failure"),
        _run("Frontend", status="in_progress", conclusion=None),
    ],
    ids=["other-sha", "fork", "pull-request", "branch", "failed", "running"],
)
def test_one_unqualified_workflow_run_blocks_the_release(tmp_path: Path, run: dict[str, Any]) -> None:
    routes = _routes(**{_runs_path("frontend.yml"): {"workflow_runs": [run]}})
    decision = candidate.qualify(_event(), REPOSITORY, _checkout(tmp_path), FakeApi(routes))

    assert (decision.qualified, decision.publish) == (False, False)
    assert "Frontend" in decision.reason


def test_a_failed_rerun_supersedes_an_earlier_success(tmp_path: Path) -> None:
    runs = [_run("Frontend"), _run("Frontend", run_attempt=2, conclusion="failure")]
    routes = _routes(**{_runs_path("frontend.yml"): {"workflow_runs": runs}})

    assert not candidate.qualify(_event(), REPOSITORY, _checkout(tmp_path), FakeApi(routes)).qualified


@pytest.mark.parametrize("status", ["behind", "diverged"])
def test_a_candidate_outside_current_master_history_does_not_qualify(tmp_path: Path, status: str) -> None:
    routes = _routes(**{f"/repos/{REPOSITORY}/compare/{SHA}...master": {"status": status}})
    decision = candidate.qualify(_event(), REPOSITORY, _checkout(tmp_path), FakeApi(routes))

    assert (decision.qualified, decision.publish) == (False, False)
    assert "master" in decision.reason


def test_duplicate_completion_events_resolve_to_the_same_candidate(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    decisions = [candidate.qualify(_event(name=name), REPOSITORY, checkout, FakeApi(_routes())) for name in WORKFLOWS]

    assert len({(item.sha, item.tag, item.publish, item.notes) for item in decisions}) == 1


def test_an_already_published_version_is_skipped_even_from_a_later_commit(tmp_path: Path) -> None:
    release = {"draft": False, "tag_name": "v1.0.0", "target_commitish": OTHER_SHA}
    routes = _routes(**{f"/repos/{REPOSITORY}/releases/tags/v1.0.0": release})
    decision = candidate.qualify(_event(), REPOSITORY, _checkout(tmp_path), FakeApi(routes))

    assert (decision.qualified, decision.publish) == (True, False)
    assert "already published" in decision.reason


def test_an_unpublished_tag_on_another_commit_fails_closed(tmp_path: Path) -> None:
    ref = {"object": {"type": "commit", "sha": OTHER_SHA}}
    routes = _routes(**{f"/repos/{REPOSITORY}/git/ref/tags/v1.0.0": ref})

    with pytest.raises(candidate.QualificationError, match=r"v1.0.0"):
        candidate.qualify(_event(), REPOSITORY, _checkout(tmp_path), FakeApi(routes))


def test_an_annotated_tag_is_resolved_to_its_commit(tmp_path: Path) -> None:
    routes = _routes(
        **{
            f"/repos/{REPOSITORY}/git/ref/tags/v1.0.0": {"object": {"type": "tag", "sha": "c" * 40}},
            f"/repos/{REPOSITORY}/git/tags/{'c' * 40}": {"object": {"type": "commit", "sha": SHA}},
        }
    )

    assert candidate.qualify(_event(), REPOSITORY, _checkout(tmp_path), FakeApi(routes)).publish


def test_a_draft_for_another_candidate_fails_closed_and_a_matching_draft_resumes() -> None:
    other = {"draft": True, "tag_name": "v1.0.0", "target_commitish": OTHER_SHA}
    matching = {"draft": True, "tag_name": "v1.0.0", "target_commitish": SHA}

    with pytest.raises(candidate.QualificationError, match="Draft"):
        candidate.publication_state(
            FakeApi(_routes(**{f"/repos/{REPOSITORY}/releases?per_page=100": [other]})), REPOSITORY, "v1.0.0", SHA
        )
    state = candidate.publication_state(
        FakeApi(_routes(**{f"/repos/{REPOSITORY}/releases?per_page=100": [matching]})), REPOSITORY, "v1.0.0", SHA
    )
    assert state == "pending"


def test_a_missing_changelog_heading_fails_a_release_version(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path, changelog="# Changelog\n\n## [0.9.2] - 2026-11-23\n\n- Older.\n")

    with pytest.raises(candidate.QualificationError, match=r"1\.0\.0"):
        candidate.qualify(_event(), REPOSITORY, checkout, FakeApi(_routes()))


def test_an_empty_changelog_section_fails_a_release_version(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path, changelog="# Changelog\n\n## [1.0.0] - 2026-11-24\n\n## [0.9.2] - 2026-11-23\n")

    with pytest.raises(candidate.QualificationError):
        candidate.qualify(_event(), REPOSITORY, checkout, FakeApi(_routes()))


def test_inconsistent_package_versions_fail_a_release_version(tmp_path: Path) -> None:
    with pytest.raises(candidate.QualificationError, match=r"frontend/package.json"):
        candidate.qualify(_event(), REPOSITORY, _checkout(tmp_path, frontend="0.9.2"), FakeApi(_routes()))


def test_a_pre_release_version_skips_publication_during_workflow_rollout(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path, version="0.9.2", changelog="# Changelog\n", frontend="0.9.1")
    decision = candidate.qualify(_event(), REPOSITORY, checkout, FakeApi(_routes()))

    assert (decision.qualified, decision.publish, decision.version) == (True, False, "0.9.2")


def test_api_failures_propagate_as_errors(tmp_path: Path) -> None:
    routes = _routes(**{_runs_path("backend.yml"): candidate.QualificationError("GitHub API returned HTTP 502")})

    with pytest.raises(candidate.QualificationError, match="502"):
        candidate.qualify(_event(), REPOSITORY, _checkout(tmp_path), FakeApi(routes))


@contextmanager
def _github(status: int, body: object) -> Iterator[tuple[str, list[dict[str, str]]]]:
    """Serve one fixed JSON response on loopback and record request headers."""
    seen: list[dict[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        """Answer every GET with the fixed response."""

        def do_GET(self) -> None:
            """Record headers and reply."""
            seen.append(dict(self.headers.items()))
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            """Keep test output quiet."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


@pytest.mark.parametrize(
    ("status", "check"),
    [
        (200, lambda value: value == {"status": "ahead"}),
        (404, lambda value: value is None),
    ],
)
def test_the_github_client_reads_json_and_maps_404_to_none(status: int, check: Callable[[object], bool]) -> None:
    with _github(status, {"status": "ahead"}) as (origin, seen):
        assert check(candidate.GitHubApi(origin, "job-token")("/repos/x/y"))
    assert seen[0]["Authorization"] == "Bearer job-token"


@pytest.mark.parametrize("status", [401, 403, 500])
def test_the_github_client_raises_on_other_http_errors(status: int) -> None:
    with (
        _github(status, {"message": "no"}) as (origin, _),
        pytest.raises(candidate.QualificationError, match=str(status)),
    ):
        candidate.GitHubApi(origin, "job-token")("/repos/x/y")


def test_the_cli_writes_outputs_and_utf8_notes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "checkout").mkdir()
    checkout = _checkout(tmp_path / "checkout")
    event = tmp_path / "event.json"
    event.write_text(json.dumps(_event()), encoding="utf-8")
    output = tmp_path / "output.txt"
    notes = tmp_path / "notes.md"
    monkeypatch.setattr(candidate, "GitHubApi", lambda *_: FakeApi(_routes()))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_TOKEN", "job-token")

    status = candidate.main(
        ["qualify", "--event", str(event), "--repository", REPOSITORY, "--root", str(checkout), "--notes", str(notes)]
    )

    assert status == 0
    lines = output.read_text(encoding="utf-8").splitlines()
    assert {"qualified=true", "publish=true", f"sha={SHA}", "version=1.0.0", "tag=v1.0.0"} <= set(lines)
    assert "“quoted”" in notes.read_bytes().decode("utf-8")
