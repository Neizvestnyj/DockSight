"""Exercise release publication against in-memory GitHub and registry fakes, never production."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import sys
import tarfile
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest
import yaml

ROOT: Final = Path(__file__).resolve().parents[3]
REPOSITORY: Final = "Neizvestnyj/DockSight"
SOURCE: Final = f"https://github.com/{REPOSITORY}"
NAMESPACE: Final = "neizvestnyj"
SHA: Final = "a" * 40
OTHER_SHA: Final = "b" * 40
VERSION: Final = "1.0.0"
TAG: Final = "v1.0.0"
UPLOADS: Final = "https://uploads.github.com"


def _load(name: str) -> ModuleType:
    """Import a release script with its sibling modules importable."""
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


publish = _load("publish_release")


def _digest(data: bytes) -> str:
    """Return an OCI sha256 digest."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _add(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    """Add one in-memory file to a tar archive."""
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def _archive(path: Path, component: str, arch: str, sha: str = SHA, version: str = VERSION) -> Path:
    """Write a minimal single-platform OCI image archive like buildx's OCI exporter."""
    labels = {
        "org.opencontainers.image.source": SOURCE,
        "org.opencontainers.image.revision": sha,
        "org.opencontainers.image.version": version,
        "org.opencontainers.image.title": f"docksight-{component}",
    }
    config = json.dumps({"architecture": arch, "os": "linux", "config": {"Labels": labels}}).encode()
    manifest = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": _digest(config)},
            "layers": [],
        }
    ).encode()
    index = json.dumps(
        {
            "schemaVersion": 2,
            "manifests": [
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": _digest(manifest),
                    "size": len(manifest),
                    "platform": {"os": "linux", "architecture": arch},
                }
            ],
        }
    ).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w") as tar:
        _add(tar, "oci-layout", b'{"imageLayoutVersion":"1.0.0"}')
        _add(tar, "index.json", index)
        for blob in (config, manifest):
            _add(tar, f"blobs/sha256/{_digest(blob).removeprefix('sha256:')}", blob)
    return path


def _archives(directory: Path, sha: str = SHA) -> Path:
    """Write the build-job artifacts of both architectures."""
    for arch in publish.ARCHES:
        for component in publish.COMPONENTS:
            _archive(directory / f"images-{arch}" / f"{component}.tar", component, arch, sha)
    return directory


class FakeRegistry:
    """Store manifests and configs in memory and fail selected pushes."""

    def __init__(self, fail_push: str = "") -> None:
        """Start empty; pushes to a reference containing fail_push raise."""
        self.manifests: dict[str, bytes] = {}
        self.configs: dict[str, object] = {}
        self.public: set[str] = set()
        self.fail_push = fail_push
        self.pushes: list[str] = []
        self.indexes: list[str] = []

    def manifest(self, reference: str, anonymous: bool = False) -> bytes | None:
        """Return raw manifest bytes by tag, digest, or tag-and-digest reference."""
        base, _, digest = reference.partition("@")
        name = base.split(":")[0]
        if anonymous and name not in self.public:
            return None
        return self.manifests.get(f"{name}@{digest}" if digest else reference)

    def config(self, reference: str) -> object:
        """Return the config of a platform manifest."""
        manifest = json.loads(self.manifests[reference])
        return self.configs[manifest["config"]["digest"]]

    def push(self, archive: Path, reference: str) -> None:
        """Copy the archive's manifest and config, preserving the digest."""
        if self.fail_push and self.fail_push in reference:
            raise publish.ReleaseError(f"push failed for {reference}")
        loaded = publish.read_archive(archive)
        assert reference.endswith(loaded.digest)
        self.manifests[reference] = loaded.manifest
        self.configs[loaded.config_digest] = loaded.config
        self.pushes.append(reference)

    def create_index(self, tag: str, sources: Sequence[str]) -> None:
        """Assemble an OCI index from pushed platform manifests."""
        entries = []
        for source in sources:
            config = self.config(source)
            assert isinstance(config, dict)
            entries.append(
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": source.split("@")[1],
                    "platform": {"os": config["os"], "architecture": config["architecture"]},
                }
            )
        index = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json", "manifests": entries}
        self.manifests[tag] = json.dumps(index).encode()
        self.manifests[f"{tag.split(':v')[0]}@{_digest(self.manifests[tag])}"] = self.manifests[tag]
        self.indexes.append(tag)


class FakeGitHub:
    """Model releases, assets, and tags of one repository in memory."""

    def __init__(self) -> None:
        """Start with no releases or tags."""
        self.releases: dict[int, dict[str, Any]] = {}
        self.tags: dict[str, str] = {}
        self.writes: list[tuple[str, str]] = []
        self.next_id = 1

    def add_release(self, tag: str, target: str, draft: bool) -> dict[str, Any]:
        """Create a release directly, tagging it when published."""
        release_id = self.next_id
        self.next_id += 1
        release = {
            "id": release_id,
            "tag_name": tag,
            "target_commitish": target,
            "draft": draft,
            "prerelease": False,
            "assets": [],
            "upload_url": f"{UPLOADS}/repos/{REPOSITORY}/releases/{release_id}/assets{{?name,label}}",
        }
        self.releases[release_id] = release
        if not draft:
            self.tags.setdefault(tag, target)
        return release

    def __call__(self, path: str) -> object | None:
        """Serve GET requests."""
        prefix = f"/repos/{REPOSITORY}"
        published = [item for item in self.releases.values() if not item["draft"]]
        routes: dict[str, object] = {f"{prefix}/releases?per_page=100": list(self.releases.values())}
        for item in published:
            routes[f"{prefix}/releases/tags/{item['tag_name']}"] = item
        for tag, sha in self.tags.items():
            routes[f"{prefix}/git/ref/tags/{tag}"] = {"object": {"type": "commit", "sha": sha}}
        for release_id, item in self.releases.items():
            routes[f"{prefix}/releases/{release_id}"] = item
            routes[f"{prefix}/releases/{release_id}/assets"] = item["assets"]
        return routes.get(path)

    def send(
        self,
        method: str,
        path: str,
        payload: object | None = None,
        data: bytes | None = None,
        content_type: str = "application/json",
    ) -> object | None:
        """Apply a write to the in-memory repository."""
        self.writes.append((method, path))
        prefix = f"/repos/{REPOSITORY}/releases"
        if method == "POST" and path == prefix:
            return self._create(payload)
        if method == "PATCH" and path.startswith(f"{prefix}/"):
            return self._update(int(path.rsplit("/", 1)[1]), payload)
        if method == "DELETE" and path.startswith(f"{prefix}/assets/"):
            self._delete_asset(int(path.rsplit("/", 1)[1]))
            return None
        if method == "POST" and path.startswith(UPLOADS) and data is not None:
            return self._upload(path, data)
        raise AssertionError(f"unexpected write {method} {path}")

    def _create(self, payload: object) -> dict[str, Any]:
        """Create a release from a JSON payload."""
        assert isinstance(payload, dict)
        release = self.add_release(payload["tag_name"], payload["target_commitish"], payload["draft"])
        release.update(payload)
        return release

    def _update(self, release_id: int, payload: object) -> dict[str, Any]:
        """Update a release and create its tag when it is published."""
        assert isinstance(payload, dict)
        release = self.releases[release_id]
        release.update(payload)
        if not release["draft"]:
            self.tags.setdefault(release["tag_name"], release["target_commitish"])
        return release

    def _delete_asset(self, asset_id: int) -> None:
        """Remove an asset from every release."""
        for release in self.releases.values():
            release["assets"] = [item for item in release["assets"] if item["id"] != asset_id]

    def _upload(self, path: str, data: bytes) -> dict[str, Any]:
        """Attach uploaded bytes as a release asset."""
        release = self.releases[int(path.split("/releases/")[1].split("/")[0])]
        asset = {
            "id": 1000 + self.next_id,
            "name": path.split("?name=")[1],
            "size": len(data),
            "state": "uploaded",
            "digest": _digest(data),
        }
        self.next_id += 1
        release["assets"].append(asset)
        return asset


def _assets(directory: Path, backend: str, frontend: str, installer_compose: bytes | None = None) -> Path:
    """Write rendered installation assets referencing the published images."""
    directory.mkdir(parents=True, exist_ok=True)
    template = (ROOT / "deploy/compose.yaml").read_text(encoding="utf-8")
    rendered = template.replace(
        "${DOCKSIGHT_BACKEND_IMAGE:?Set DOCKSIGHT_BACKEND_IMAGE to the backend image reference}", backend
    ).replace("${DOCKSIGHT_FRONTEND_IMAGE:?Set DOCKSIGHT_FRONTEND_IMAGE to the frontend image reference}", frontend)
    (directory / "compose.yaml").write_bytes(rendered.encode())
    for name in ("docksight.env.example", "INSTALL.md"):
        (directory / name).write_bytes((ROOT / "deploy" / name).read_bytes())
    checksum = hashlib.sha256(installer_compose or rendered.encode()).hexdigest()
    for name in ("install.sh", "install.ps1"):
        installer = (ROOT / "deploy" / name).read_bytes()
        installer = installer.replace(b"__DOCKSIGHT_RELEASE_TAG__", TAG.encode())
        (directory / name).write_bytes(installer.replace(b"__DOCKSIGHT_COMPOSE_SHA256__", checksum.encode()))
    return directory


def _publish_images(registry: FakeRegistry, archives: Path) -> dict[str, str]:
    """Run the image publication step for the standard candidate."""
    return publish.publish_images(registry, archives, NAMESPACE, REPOSITORY, SHA, VERSION)


def _image_refs(digests: dict[str, str]) -> dict[str, str]:
    """Map components to tag-and-digest references."""
    return {name: f"ghcr.io/{NAMESPACE}/docksight-{name}:{TAG}@{digest}" for name, digest in digests.items()}


def _release(github: FakeGitHub, registry: FakeRegistry, assets: Path, refs: dict[str, str], release_id: int) -> None:
    """Run the final release step."""
    publish.publish_release(github, registry, REPOSITORY, SHA, VERSION, release_id, assets, refs)


def _public(registry: FakeRegistry) -> None:
    """Mark both packages anonymously readable."""
    registry.public |= {f"ghcr.io/{NAMESPACE}/docksight-{name}" for name in publish.COMPONENTS}


def test_full_publication_creates_a_draft_then_images_then_a_public_release(tmp_path: Path) -> None:
    github, registry = FakeGitHub(), FakeRegistry()
    state, release_id = publish.ensure_draft(github, REPOSITORY, TAG, SHA, "### Added\n\n- Compose.\n")
    assert state == "pending" and github.releases[release_id]["draft"] is True
    assert TAG not in github.tags

    digests = _publish_images(registry, _archives(tmp_path / "images"))
    assert len(registry.pushes) == 4 and len(registry.indexes) == 2
    _public(registry)
    refs = _image_refs(digests)
    _release(github, registry, _assets(tmp_path / "assets", refs["backend"], refs["frontend"]), refs, release_id)

    release = github.releases[release_id]
    assert release["draft"] is False and release["make_latest"] == "true"
    assert github.tags[TAG] == SHA
    names = sorted(asset["name"] for asset in release["assets"])
    assert names == ["INSTALL.md", "compose.yaml", "docksight.env.example", "install.ps1", "install.sh"]


def test_index_platforms_match_the_tested_archive_digests(tmp_path: Path) -> None:
    registry = FakeRegistry()
    archives = _archives(tmp_path / "images")
    digests = _publish_images(registry, archives)

    index = json.loads(registry.manifests[f"ghcr.io/{NAMESPACE}/docksight-backend:{TAG}"])
    tested = {
        f"linux/{arch}": publish.read_archive(archives / f"images-{arch}" / "backend.tar").digest
        for arch in publish.ARCHES
    }
    assert {f"linux/{m['platform']['architecture']}": m["digest"] for m in index["manifests"]} == tested
    assert digests["backend"] == _digest(registry.manifests[f"ghcr.io/{NAMESPACE}/docksight-backend:{TAG}"])


def test_an_archive_built_for_another_commit_is_never_pushed(tmp_path: Path) -> None:
    registry = FakeRegistry()
    archives = _archives(tmp_path / "images")
    _archive(archives / "images-arm64" / "backend.tar", "backend", "arm64", sha=OTHER_SHA)

    with pytest.raises(publish.ReleaseError, match="revision"):
        _publish_images(registry, archives)
    assert registry.pushes == []


def test_a_missing_architecture_archive_publishes_nothing(tmp_path: Path) -> None:
    registry = FakeRegistry()
    archives = _archives(tmp_path / "images")
    (archives / "images-arm64" / "frontend.tar").unlink()

    with pytest.raises(FileNotFoundError):
        _publish_images(registry, archives)
    assert registry.pushes == [] and registry.indexes == []


def test_a_failed_second_image_push_leaves_a_recoverable_draft_and_a_retry_resumes(tmp_path: Path) -> None:
    github, registry = FakeGitHub(), FakeRegistry(fail_push="docksight-frontend")
    _, release_id = publish.ensure_draft(github, REPOSITORY, TAG, SHA, "Notes\n")
    archives = _archives(tmp_path / "images")

    with pytest.raises(publish.ReleaseError, match="push failed"):
        _publish_images(registry, archives)
    assert github.releases[release_id]["draft"] is True and TAG not in github.tags
    assert registry.indexes == [f"ghcr.io/{NAMESPACE}/docksight-backend:{TAG}"]

    registry.fail_push = ""
    pushes_before = len(registry.pushes)
    assert publish.ensure_draft(github, REPOSITORY, TAG, SHA, "Notes\n") == ("pending", release_id)
    digests = _publish_images(registry, archives)
    assert all("docksight-frontend" in reference for reference in registry.pushes[pushes_before:])
    assert set(digests) == set(publish.COMPONENTS)


def test_an_existing_image_tag_from_another_commit_fails_without_overwriting(tmp_path: Path) -> None:
    registry = FakeRegistry()
    publish.publish_images(registry, _archives(tmp_path / "old", OTHER_SHA), NAMESPACE, REPOSITORY, OTHER_SHA, VERSION)
    existing = dict(registry.manifests)
    indexes = list(registry.indexes)

    with pytest.raises(publish.ReleaseError, match="revision"):
        _publish_images(registry, _archives(tmp_path / "new"))
    assert registry.manifests == existing and registry.indexes == indexes


def test_an_existing_single_platform_tag_is_rejected(tmp_path: Path) -> None:
    registry = FakeRegistry()
    archives = _archives(tmp_path / "images")
    name = f"ghcr.io/{NAMESPACE}/docksight-backend"
    amd64 = publish.read_archive(archives / "images-amd64" / "backend.tar")
    registry.push(amd64.path, f"{name}@{amd64.digest}")
    registry.create_index(f"{name}:{TAG}", [f"{name}@{amd64.digest}"])

    with pytest.raises(publish.ReleaseError, match="platforms"):
        _publish_images(registry, archives)


def test_private_packages_keep_the_draft_and_name_the_visibility_change(tmp_path: Path) -> None:
    github, registry = FakeGitHub(), FakeRegistry()
    _, release_id = publish.ensure_draft(github, REPOSITORY, TAG, SHA, "Notes\n")
    refs = _image_refs(_publish_images(registry, _archives(tmp_path / "images")))
    assets = _assets(tmp_path / "assets", refs["backend"], refs["frontend"])

    with pytest.raises(publish.ReleaseError, match=r"docksight-backend.*public"):
        _release(github, registry, assets, refs, release_id)
    assert github.releases[release_id]["draft"] is True and TAG not in github.tags

    _public(registry)
    _release(github, registry, assets, refs, release_id)
    assert github.tags[TAG] == SHA


def test_compose_assets_must_pin_the_published_digests(tmp_path: Path) -> None:
    github, registry = FakeGitHub(), FakeRegistry()
    _, release_id = publish.ensure_draft(github, REPOSITORY, TAG, SHA, "Notes\n")
    refs = _image_refs(_publish_images(registry, _archives(tmp_path / "images")))
    _public(registry)
    assets = _assets(tmp_path / "assets", f"ghcr.io/{NAMESPACE}/docksight-backend:{TAG}", refs["frontend"])

    with pytest.raises(publish.ReleaseError, match=r"compose.yaml"):
        _release(github, registry, assets, refs, release_id)
    assert github.releases[release_id]["draft"] is True


@pytest.mark.parametrize("installer", ["install.sh", "install.ps1"])
def test_installers_must_embed_the_tag_and_the_published_compose_checksum(tmp_path: Path, installer: str) -> None:
    github, registry = FakeGitHub(), FakeRegistry()
    _, release_id = publish.ensure_draft(github, REPOSITORY, TAG, SHA, "Notes\n")
    refs = _image_refs(_publish_images(registry, _archives(tmp_path / "images")))
    _public(registry)
    assets = _assets(tmp_path / "assets", refs["backend"], refs["frontend"], installer_compose=b"stale compose")
    good = _assets(tmp_path / "good", refs["backend"], refs["frontend"])
    other = "install.ps1" if installer == "install.sh" else "install.sh"
    (assets / other).write_bytes((good / other).read_bytes())

    with pytest.raises(publish.ReleaseError, match=re.escape(installer)):
        _release(github, registry, assets, refs, release_id)
    assert github.releases[release_id]["draft"] is True

    (assets / installer).write_bytes((ROOT / "deploy" / installer).read_bytes())
    with pytest.raises(publish.ReleaseError, match="placeholder"):
        _release(github, registry, assets, refs, release_id)


def test_retried_asset_upload_keeps_identical_assets_and_replaces_changed_ones(tmp_path: Path) -> None:
    github, registry = FakeGitHub(), FakeRegistry()
    _, release_id = publish.ensure_draft(github, REPOSITORY, TAG, SHA, "Notes\n")
    refs = _image_refs(_publish_images(registry, _archives(tmp_path / "images")))
    _public(registry)
    assets = _assets(tmp_path / "assets", refs["backend"], refs["frontend"])
    upload = github.releases[release_id]["upload_url"].split("{")[0]
    github.send("POST", f"{upload}?name=INSTALL.md", data=(assets / "INSTALL.md").read_bytes())
    github.send("POST", f"{upload}?name=compose.yaml", data=b"stale")
    github.writes.clear()

    _release(github, registry, assets, refs, release_id)

    uploads = [path.split("?name=")[1] for method, path in github.writes if path.startswith(UPLOADS)]
    assert sorted(uploads) == ["compose.yaml", "docksight.env.example", "install.ps1", "install.sh"]
    assert sum(method == "DELETE" for method, _ in github.writes) == 1


def test_a_rerun_after_publication_is_a_no_op(tmp_path: Path) -> None:
    github = FakeGitHub()
    github.add_release(TAG, SHA, draft=False)

    assert publish.ensure_draft(github, REPOSITORY, TAG, SHA, "Notes\n") == ("published", None)
    assert github.writes == []


def test_a_conflicting_git_tag_fails_closed_before_any_write() -> None:
    github = FakeGitHub()
    github.tags[TAG] = OTHER_SHA

    with pytest.raises(publish.ReleaseError, match=re.escape(TAG)):
        publish.ensure_draft(github, REPOSITORY, TAG, SHA, "Notes\n")
    assert github.writes == []


@pytest.mark.parametrize(
    ("published", "latest"), [(["v1.1.0"], "false"), (["v0.9.0", "v0.10.0"], "true"), ([], "true")]
)
def test_an_older_version_finishing_late_does_not_become_latest(published: list[str], latest: str) -> None:
    github = FakeGitHub()
    for tag in published:
        github.add_release(tag, OTHER_SHA, draft=False)

    assert publish.make_latest(github, REPOSITORY, VERSION) == latest


def test_the_loaded_image_must_be_the_tested_archive(tmp_path: Path) -> None:
    archive = publish.read_archive(_archive(tmp_path / "backend.tar", "backend", "amd64"))

    publish.check_loaded(archive, archive.digest)
    publish.check_loaded(archive, archive.config_digest)
    with pytest.raises(publish.ReleaseError, match="loaded"):
        publish.check_loaded(archive, _digest(b"other"))


def test_release_workflow_limits_write_permissions_to_qualified_publication_jobs() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    jobs: dict[str, Any] = workflow["jobs"]

    assert workflow["permissions"] == {}
    assert set(workflow[True]) == {"workflow_run"}
    assert workflow["concurrency"] == {"group": "release", "cancel-in-progress": False, "queue": "max"}
    writers = {name: job["permissions"] for name, job in jobs.items() if "write" in job["permissions"].values()}
    assert writers == {
        "draft": {"contents": "write"},
        "images": {"contents": "read", "packages": "write"},
        "release": {"contents": "write"},
    }
    assert jobs["qualify"]["permissions"] == {"actions": "read", "contents": "read"}
    assert jobs["build"]["permissions"] == {"contents": "read"}
    assert {item["arch"] for item in jobs["build"]["strategy"]["matrix"]["include"]} == set(publish.ARCHES)
    assert set(jobs["draft"]["needs"]) >= {"qualify", "build"}
    assert set(jobs["images"]["needs"]) >= {"qualify", "draft"}
    assert set(jobs["release"]["needs"]) >= {"qualify", "draft", "images"}
    assert "needs.qualify.outputs.publish == 'true'" in jobs["build"]["if"]
    assert "needs.draft.outputs.state == 'pending'" in jobs["images"]["if"]
    assert not any(job.get("continue-on-error") for job in jobs.values())


def test_build_archives_load_into_the_runner_classic_image_store() -> None:
    """Docker 28 without the containerd store rejects OCI exporter tarballs, so builds use the docker exporter."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    build = "\n".join(step.get("run", "") for step in workflow["jobs"]["build"]["steps"])

    assert '--output "type=docker,dest=' in build
    assert "type=oci" not in build


def test_release_artifacts_can_be_replaced_when_all_jobs_are_rerun() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    uploads = [
        step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]

    assert len(uploads) == 2
    assert all(step["with"].get("overwrite") is True for step in uploads)
