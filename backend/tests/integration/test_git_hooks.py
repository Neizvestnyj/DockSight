"""Exercise branch protection through real Git hooks in disposable repositories."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest
import yaml

ROOT: Final = Path(__file__).resolve().parents[3]


def _run(directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run a bounded command without inheriting the caller's Git repository selection."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.pop("SKIP", None)
    environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return subprocess.run(
        arguments, cwd=directory, env=environment, capture_output=True, text=True, timeout=60, check=False
    )


def _repository(directory: Path, branch: str = "feature/test") -> Path:
    """Install the project's branch guards in a repository containing only a seed commit."""
    directory.mkdir()
    assert _run(directory, "git", "init", "-b", branch).returncode == 0
    for key, value in (("user.name", "Hook Test"), ("user.email", "hooks@example.invalid")):
        assert _run(directory, "git", "config", key, value).returncode == 0
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    repositories = [
        {**repository, "hooks": [hook for hook in repository["hooks"] if hook["id"] == "no-commit-to-branch"]}
        for repository in config["repos"]
    ]
    config["repos"] = [repository for repository in repositories if repository["hooks"]]
    (directory / ".pre-commit-config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8", newline="\n")
    (directory / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/git_hooks.py", directory / "scripts/git_hooks.py")
    assert _run(directory, "git", "add", ".").returncode == 0
    assert _run(directory, "git", "commit", "-m", "test: seed repository").returncode == 0
    installed = _run(directory, sys.executable, "scripts/git_hooks.py", "install")
    assert installed.returncode == 0, installed.stdout + installed.stderr
    return directory


@pytest.mark.parametrize(("branch", "allowed"), [("master", False), ("feature/test", True)])
def test_commit_guard_checks_branch_even_for_empty_commits(tmp_path: Path, branch: str, allowed: bool) -> None:
    repository = _repository(tmp_path / "work tree", branch)
    committed = _run(repository, "git", "commit", "--allow-empty", "-m", "test: guarded commit")
    assert (committed.returncode == 0) is allowed, committed.stdout + committed.stderr
    if not allowed:
        assert _run(repository, "git", "rev-list", "--count", "HEAD").stdout.strip() == "1"


@pytest.mark.parametrize(
    ("branch", "refspecs", "allowed"),
    [
        ("feature/test", ("HEAD:refs/heads/master",), False),
        ("feature/test", ("HEAD:refs/heads/feature/test", "HEAD:refs/heads/master"), False),
        ("feature/test", ("HEAD:refs/heads/feature/test",), True),
        ("master", ("HEAD:refs/heads/feature/test",), True),
        ("feature/test", ("HEAD:refs/tags/master",), True),
    ],
)
def test_push_guard_checks_every_remote_target(
    tmp_path: Path, branch: str, refspecs: tuple[str, ...], allowed: bool
) -> None:
    repository = _repository(tmp_path / "work", branch)
    remote = tmp_path / "remote.git"
    assert _run(tmp_path, "git", "init", "--bare", str(remote)).returncode == 0
    pushed = _run(repository, "git", "push", str(remote), *refspecs)
    assert (pushed.returncode == 0) is allowed, pushed.stdout + pushed.stderr
    refs = _run(tmp_path, "git", "--git-dir", str(remote), "show-ref").stdout
    if not allowed:
        assert refs == ""
        assert "Direct pushes to master are prohibited." in pushed.stderr


def test_push_guard_rejects_master_deletion(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "work")
    remote = tmp_path / "remote.git"
    assert _run(tmp_path, "git", "init", "--bare", str(remote)).returncode == 0
    revision = _run(repository, "git", "rev-parse", "HEAD").stdout.strip()
    assert _run(repository, "git", "push", str(remote), "HEAD:refs/heads/feature/test").returncode == 0
    assert _run(tmp_path, "git", "--git-dir", str(remote), "update-ref", "refs/heads/master", revision).returncode == 0
    pushed = _run(repository, "git", "push", str(remote), ":refs/heads/master")
    assert pushed.returncode != 0
    assert "Direct pushes to master are prohibited." in pushed.stderr
    assert _run(tmp_path, "git", "--git-dir", str(remote), "rev-parse", "refs/heads/master").stdout.strip() == revision


def test_installation_preserves_an_existing_push_hook(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "work")
    hook = repository / ".git/hooks/pre-push"
    custom_hook = "#!/bin/sh\nexit 1\n"
    hook.write_text(custom_hook, encoding="utf-8", newline="\n")
    installed = _run(repository, sys.executable, "scripts/git_hooks.py", "install")
    assert installed.returncode != 0
    assert hook.read_text(encoding="utf-8") == custom_hook


def test_hook_installation_is_repeatable(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "work")
    installed = _run(repository, sys.executable, "scripts/git_hooks.py", "install")
    assert installed.returncode == 0, installed.stdout + installed.stderr


@pytest.mark.parametrize("name", ["pre-commit", "commit-msg"])
def test_installation_preserves_conflicting_legacy_hooks(tmp_path: Path, name: str) -> None:
    repository = _repository(tmp_path / "work")
    hook = repository / ".git/hooks" / name
    legacy = hook.with_name(f"{name}.legacy")
    original_hook = "#!/bin/sh\necho custom hook\n"
    original_legacy = "#!/bin/sh\necho older hook\n"
    hook.write_text(original_hook, encoding="utf-8", newline="\n")
    legacy.write_text(original_legacy, encoding="utf-8", newline="\n")
    installed = _run(repository, sys.executable, "scripts/git_hooks.py", "install")
    assert installed.returncode != 0
    assert hook.read_text(encoding="utf-8") == original_hook
    assert legacy.read_text(encoding="utf-8") == original_legacy
