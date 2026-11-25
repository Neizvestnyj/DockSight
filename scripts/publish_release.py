"""Publish a qualified DockSight release: a draft, the tested images, and the installation assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, cast

from release_candidate import (
    SHA_PATTERN,
    QualificationError,
    field,
    github_api,
    items,
    parse_version,
    publication_state,
    required,
    tag_commit,
    text,
    write_outputs,
)

COMPONENTS: Final[tuple[str, ...]] = ("backend", "frontend")
ARCHES: Final[tuple[str, ...]] = ("amd64", "arm64")
ASSETS: Final[tuple[str, ...]] = (
    "compose.yaml",
    "docksight.env.example",
    "INSTALL.md",
    "install.sh",
    "install.ps1",
)
INSTALLERS: Final[tuple[str, ...]] = ("install.sh", "install.ps1")
PLACEHOLDERS: Final[tuple[str, ...]] = (
    "__DOCKSIGHT_RELEASE_TAG__",
    "__DOCKSIGHT_COMPOSE_SHA256__",
)
PLATFORMS: Final[frozenset[str]] = frozenset(f"linux/{arch}" for arch in ARCHES)
INDEX_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    }
)
DIGEST_PATTERN: Final[re.Pattern[str]] = re.compile(r"sha256:[0-9a-f]{64}")
COMMAND_TIMEOUT: Final[int] = 900
TAG_PATTERN: Final[re.Pattern[str]] = re.compile(r"v(\d+\.\d+\.\d+)")


class ReleaseError(QualificationError):
    """Publication cannot continue without risking a broken or conflicting release."""


class Client(Protocol):
    """Read and write GitHub REST resources."""

    def __call__(self, path: str) -> object | None:
        """Return decoded JSON, or None for 404."""
        ...

    def send(
        self,
        method: str,
        path: str,
        payload: object | None = None,
        data: bytes | None = None,
        content_type: str = "application/json",
    ) -> object | None:
        """Write a JSON payload or raw bytes."""
        ...


class Registry(Protocol):
    """Read and write OCI manifests in a container registry."""

    def manifest(self, reference: str, anonymous: bool = False) -> bytes | None:
        """Return raw manifest bytes, or None when the reference is unknown or not readable."""
        ...

    def config(self, reference: str) -> object:
        """Return the image config JSON of a platform manifest."""
        ...

    def push(self, archive: Path, reference: str) -> None:
        """Copy a single-platform OCI archive to a digest reference without changing its digest."""
        ...

    def create_index(self, tag: str, sources: Sequence[str]) -> None:
        """Create a multi-platform index tag from pushed platform manifests."""
        ...


@dataclass(frozen=True)
class Archive:
    """One tested single-platform OCI image archive from a build job."""

    path: Path
    digest: str
    manifest: bytes
    config_digest: str
    config: object

    @property
    def platform(self) -> str:
        """Return the os/architecture pair recorded in the image config."""
        return f"{text(self.config, 'os')}/{text(self.config, 'architecture')}"

    @property
    def labels(self) -> Mapping[str, object]:
        """Return the image labels."""
        return image_labels(self.config)


def digest(data: bytes) -> str:
    """Return the OCI sha256 digest of bytes."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def image_labels(config: object) -> Mapping[str, object]:
    """Read labels from an image config."""
    labels = field(config, "config", "Labels")
    if not isinstance(labels, dict):
        raise ReleaseError("Image config has no labels")
    return cast(dict[str, object], labels)


def _blob(tar: tarfile.TarFile, expected: str) -> bytes:
    """Read a content-addressed blob and verify its digest."""
    member = tar.extractfile(f"blobs/sha256/{expected.removeprefix('sha256:')}")
    if member is None:
        raise ReleaseError(f"OCI archive lacks blob {expected}")
    data = member.read()
    if digest(data) != expected:
        raise ReleaseError(f"OCI archive blob {expected} does not match its digest")
    return data


def read_archive(path: Path) -> Archive:
    """Read the single manifest and config of a buildx OCI archive."""
    with tarfile.open(path) as tar:
        index_file = tar.extractfile("index.json")
        if index_file is None:
            raise ReleaseError(f"{path} is not an OCI archive")
        manifests = items(json.loads(index_file.read()), "manifests")
        if len(manifests) != 1:
            raise ReleaseError(f"{path} must contain exactly one image manifest")
        manifest_digest = text(manifests[0], "digest")
        manifest = _blob(tar, manifest_digest)
        config_digest = text(json.loads(manifest), "config", "digest")
        config: object = json.loads(_blob(tar, config_digest))
    return Archive(path, manifest_digest, manifest, config_digest, config)


def expected_labels(
    component: str, repository: str, sha: str, version: str
) -> dict[str, str]:
    """Return the labels that identify a release image."""
    return {
        "org.opencontainers.image.source": f"https://github.com/{repository}",
        "org.opencontainers.image.revision": sha,
        "org.opencontainers.image.version": version,
        "org.opencontainers.image.title": f"docksight-{component}",
    }


def check_labels(
    labels: Mapping[str, object], expected: Mapping[str, str], subject: str
) -> None:
    """Fail when an image's source, revision, version, or identity differs from the candidate."""
    for key, value in expected.items():
        if labels.get(key) != value:
            name = key.rsplit(".", 1)[1]
            raise ReleaseError(
                f"{subject} has {name} {labels.get(key)!r}, expected {value!r}"
            )


def check_loaded(archive: Archive, image_id: str) -> None:
    """Fail unless the image loaded for the smoke test is exactly the archived image."""
    if image_id not in {archive.digest, archive.config_digest}:
        raise ReleaseError(
            f"The loaded image {image_id} is not the archived image {archive.digest}"
        )


def load_archives(
    directory: Path, component: str, repository: str, sha: str, version: str
) -> dict[str, Archive]:
    """Read and verify both architecture archives of a component before any registry write."""
    archives = {
        arch: read_archive(directory / f"images-{arch}" / f"{component}.tar")
        for arch in ARCHES
    }
    for arch, archive in archives.items():
        if archive.platform != f"linux/{arch}":
            raise ReleaseError(
                f"{archive.path} is {archive.platform}, expected linux/{arch}"
            )
        check_labels(
            archive.labels,
            expected_labels(component, repository, sha, version),
            str(archive.path),
        )
    return archives


def index_platforms(raw: bytes, subject: str) -> dict[str, str]:
    """Map each platform of a multi-platform index to its manifest digest."""
    index: object = json.loads(raw)
    if field(index, "mediaType") not in INDEX_TYPES:
        raise ReleaseError(f"{subject} is not a multi-platform index")
    entries = items(index, "manifests")
    platforms = {
        f"{text(entry, 'platform', 'os')}/{text(entry, 'platform', 'architecture')}": text(
            entry, "digest"
        )
        for entry in entries
    }
    if len(entries) != len(PLATFORMS) or frozenset(platforms) != PLATFORMS:
        raise ReleaseError(
            f"{subject} has platforms {sorted(platforms)}, expected {sorted(PLATFORMS)}"
        )
    return platforms


def verify_index(
    registry: Registry, name: str, raw: bytes, expected: Mapping[str, str]
) -> dict[str, str]:
    """Verify the platforms and image identity of every manifest in an index."""
    platforms = index_platforms(raw, name)
    for platform, manifest_digest in platforms.items():
        config = registry.config(f"{name}@{manifest_digest}")
        actual = f"{text(config, 'os')}/{text(config, 'architecture')}"
        if actual != platform:
            raise ReleaseError(
                f"{name}@{manifest_digest} is {actual}, listed as {platform}"
            )
        check_labels(image_labels(config), expected, f"{name} {platform}")
    return platforms


def publish_component(
    registry: Registry,
    name: str,
    tag: str,
    archives: Mapping[str, Archive],
    expected: Mapping[str, str],
) -> str:
    """Reuse a matching index or push the tested archives and assemble one; return the index digest."""
    existing = registry.manifest(f"{name}:{tag}")
    if existing is not None:
        verify_index(registry, name, existing, expected)
        return digest(existing)
    for archive in archives.values():
        registry.push(archive.path, f"{name}@{archive.digest}")
    registry.create_index(
        f"{name}:{tag}", [f"{name}@{archive.digest}" for archive in archives.values()]
    )
    created = registry.manifest(f"{name}:{tag}")
    if created is None:
        raise ReleaseError(f"{name}:{tag} is missing after assembly")
    platforms = verify_index(registry, name, created, expected)
    if platforms != {
        f"linux/{arch}": archive.digest for arch, archive in archives.items()
    }:
        raise ReleaseError(f"{name}:{tag} does not reference the tested image digests")
    return digest(created)


def publish_images(
    registry: Registry,
    directory: Path,
    namespace: str,
    repository: str,
    sha: str,
    version: str,
) -> dict[str, str]:
    """Publish both components and return their index digests."""
    verified = {
        component: load_archives(directory, component, repository, sha, version)
        for component in COMPONENTS
    }
    return {
        component: publish_component(
            registry,
            f"ghcr.io/{namespace}/docksight-{component}",
            f"v{version}",
            archives,
            expected_labels(component, repository, sha, version),
        )
        for component, archives in verified.items()
    }


def find_draft(api: Client, repository: str, tag: str) -> object | None:
    """Return the draft release for a tag, if any."""
    for release in items(required(api, f"/repos/{repository}/releases?per_page=100")):
        if field(release, "draft") is True and field(release, "tag_name") == tag:
            return release
    return None


def release_id(release: object) -> int:
    """Read a numeric release ID."""
    value = field(release, "id")
    if not isinstance(value, int):
        raise ReleaseError("GitHub release has no numeric id")
    return value


def ensure_draft(
    api: Client, repository: str, tag: str, sha: str, notes: str
) -> tuple[str, int | None]:
    """Create or resume the draft for this candidate, or report that the version is already published."""
    try:
        state = publication_state(api, repository, tag, sha)
    except ReleaseError:
        raise
    except QualificationError as error:
        raise ReleaseError(str(error)) from error
    if state == "published":
        return "published", None
    body = {
        "tag_name": tag,
        "target_commitish": sha,
        "name": f"DockSight {tag[1:]}",
        "body": notes,
        "draft": True,
    }
    draft = find_draft(api, repository, tag)
    if draft is None:
        return "pending", release_id(
            api.send("POST", f"/repos/{repository}/releases", body)
        )
    api.send("PATCH", f"/repos/{repository}/releases/{release_id(draft)}", body)
    return "pending", release_id(draft)


def verify_compose(path: Path, images: Mapping[str, str]) -> None:
    """Require the compose asset to pin exactly the published images and contain no build or placeholder."""
    content = path.read_text(encoding="utf-8")
    pinned = re.findall(r"^\s*image:\s*(\S+)\s*$", content, re.MULTILINE)
    if (
        sorted(pinned) != sorted(images.values())
        or "build:" in content
        or "_IMAGE:?" in content
    ):
        raise ReleaseError(
            f"{path.name} must pin exactly {sorted(images.values())}, found {pinned}"
        )
    for reference in images.values():
        if not DIGEST_PATTERN.search(reference.rpartition("@")[2]):
            raise ReleaseError(f"{reference} is not pinned by digest")


def verify_installers(directory: Path, tag: str) -> None:
    """Require each installer to name the release tag and the checksum of the compose asset."""
    checksum = hashlib.sha256((directory / "compose.yaml").read_bytes()).hexdigest()
    for name in INSTALLERS:
        content = (directory / name).read_text(encoding="utf-8")
        if any(placeholder in content for placeholder in PLACEHOLDERS):
            raise ReleaseError(f"{name} still contains a placeholder")
        if f"'{tag}'" not in content or f"'{checksum}'" not in content:
            raise ReleaseError(
                f"{name} does not pin {tag} and the compose.yaml checksum {checksum}"
            )


def check_public(registry: Registry, images: Mapping[str, str]) -> None:
    """Fail with the packages to make public when anonymous pulls would break the installation."""
    private = [
        reference
        for reference in images.values()
        if registry.manifest(reference, anonymous=True) is None
    ]
    if private:
        names = ", ".join(
            reference.split("@")[0].rsplit(":", 1)[0] for reference in private
        )
        raise ReleaseError(
            f"Anonymous pulls fail for {names}. Make these packages public in their GitHub package settings, "
            "then rerun the failed jobs. The draft release is kept."
        )


def asset_matches(asset: object, data: bytes) -> bool:
    """Check an uploaded asset against local bytes."""
    members = cast(dict[str, object], asset) if isinstance(asset, dict) else {}
    return (
        members.get("state") == "uploaded"
        and members.get("size") == len(data)
        and members.get("digest") in {None, digest(data)}
    )


def upload_assets(
    api: Client, repository: str, release: object, directory: Path
) -> None:
    """Upload missing or changed assets to the draft and keep identical ones."""
    existing = {text(asset, "name"): asset for asset in items(release, "assets")}
    upload_url = text(release, "upload_url").split("{", 1)[0]
    for name in ASSETS:
        data = (directory / name).read_bytes()
        asset = existing.get(name)
        if asset is not None and asset_matches(asset, data):
            continue
        if asset is not None:
            api.send(
                "DELETE", f"/repos/{repository}/releases/assets/{field(asset, 'id')}"
            )
        api.send(
            "POST",
            f"{upload_url}?name={name}",
            data=data,
            content_type="application/octet-stream",
        )


def verify_assets(api: Client, repository: str, draft_id: int, directory: Path) -> None:
    """Require exactly the three release assets with matching content."""
    assets = {
        text(asset, "name"): asset
        for asset in items(
            required(api, f"/repos/{repository}/releases/{draft_id}/assets")
        )
    }
    if set(assets) != set(ASSETS):
        raise ReleaseError(
            f"Release assets are {sorted(assets)}, expected {sorted(ASSETS)}"
        )
    for name, asset in assets.items():
        if not asset_matches(asset, (directory / name).read_bytes()):
            raise ReleaseError(
                f"Uploaded asset {name} does not match the rendered file"
            )


def make_latest(api: Client, repository: str, version: str) -> str:
    """Mark the release latest only when no newer version is already published."""
    candidate = parse_version(version)
    published: list[tuple[int, int, int]] = []
    for release in items(required(api, f"/repos/{repository}/releases?per_page=100")):
        match = TAG_PATTERN.fullmatch(str(field(release, "tag_name")))
        if (
            field(release, "draft") is False
            and field(release, "prerelease") is False
            and match
        ):
            published.append(parse_version(match.group(1)))
    return "true" if all(candidate > other for other in published) else "false"


def publish_release(
    api: Client,
    registry: Registry,
    repository: str,
    sha: str,
    version: str,
    draft_id: int,
    directory: Path,
    images: Mapping[str, str],
) -> None:
    """Verify the assets and public images, then publish the draft and its tag at the candidate commit."""
    tag = f"v{version}"
    verify_compose(directory / "compose.yaml", images)
    verify_installers(directory, tag)
    check_public(registry, images)
    draft = required(api, f"/repos/{repository}/releases/{draft_id}")
    if (
        field(draft, "draft") is not True
        or field(draft, "tag_name") != tag
        or field(draft, "target_commitish") != sha
    ):
        raise ReleaseError(f"Release {draft_id} is not the draft of {tag} at {sha}")
    upload_assets(api, repository, draft, directory)
    verify_assets(api, repository, draft_id, directory)
    latest = make_latest(api, repository, version)
    api.send(
        "PATCH",
        f"/repos/{repository}/releases/{draft_id}",
        {
            "draft": False,
            "make_latest": latest,
            "tag_name": tag,
            "target_commitish": sha,
        },
    )
    if tag_commit(api, repository, tag) != sha:
        raise ReleaseError(f"Published tag {tag} does not point at {sha}")


def registry_reference(reference: str) -> str:
    """Drop the tag of a tag-and-digest reference; older skopeo rejects references with both."""
    name, separator, manifest_digest = reference.partition("@")
    if not separator:
        return reference
    repository, _, last = name.rpartition("/")
    return f"{repository}/{last.split(':', 1)[0]}@{manifest_digest}"


class SkopeoRegistry:
    """Registry operations through skopeo and Docker Buildx with credentials from prior logins."""

    def __init__(self) -> None:
        """Locate the registry tools."""
        self.skopeo = shutil.which("skopeo") or "skopeo"
        self.docker = shutil.which("docker") or "docker"

    def _run(self, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        """Run a bounded registry command."""
        return subprocess.run(
            arguments, capture_output=True, timeout=COMMAND_TIMEOUT, check=False
        )

    def manifest(self, reference: str, anonymous: bool = False) -> bytes | None:
        """Return raw manifest bytes, None when unknown or denied."""
        options = ["--no-creds"] if anonymous else []
        result = self._run(
            self.skopeo,
            "inspect",
            *options,
            "--retry-times",
            "3",
            "--raw",
            f"docker://{registry_reference(reference)}",
        )
        if result.returncode == 0:
            return result.stdout
        error = result.stderr.decode(errors="replace").lower()
        if any(
            marker in error
            for marker in (
                "manifest unknown",
                "name unknown",
                "not found",
                "unauthorized",
                "denied",
            )
        ):
            return None
        raise ReleaseError(f"Cannot read {reference}: {error.strip()[:500]}")

    def config(self, reference: str) -> object:
        """Return the image config of a platform manifest."""
        result = self._run(
            self.skopeo,
            "inspect",
            "--retry-times",
            "3",
            "--config",
            "--raw",
            f"docker://{registry_reference(reference)}",
        )
        if result.returncode != 0:
            raise ReleaseError(f"Cannot read the config of {reference}")
        config: object = json.loads(result.stdout)
        return config

    def push(self, archive: Path, reference: str) -> None:
        """Copy an OCI archive to a digest reference, failing if the digest would change."""
        result = self._run(
            self.skopeo,
            "copy",
            "--retry-times",
            "3",
            "--preserve-digests",
            f"oci-archive:{archive}",
            f"docker://{reference}",
        )
        if result.returncode != 0:
            raise ReleaseError(
                f"Cannot push {reference}: {result.stderr.decode(errors='replace').strip()[:500]}"
            )

    def create_index(self, tag: str, sources: Sequence[str]) -> None:
        """Assemble a multi-platform index tag."""
        result = self._run(
            self.docker, "buildx", "imagetools", "create", "--tag", tag, *sources
        )
        if result.returncode != 0:
            raise ReleaseError(
                f"Cannot create {tag}: {result.stderr.decode(errors='replace').strip()[:500]}"
            )


def check_sha(value: str) -> str:
    """Validate a full commit SHA argument."""
    if SHA_PATTERN.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("expected a full commit SHA")
    return value


def run_draft(arguments: argparse.Namespace) -> None:
    """Create or resume the draft release."""
    notes = Path(arguments.notes).read_text(encoding="utf-8")
    state, draft_id = ensure_draft(
        github_api(), arguments.repository, arguments.tag, arguments.sha, notes
    )
    print(f"{arguments.tag} is {state}")
    write_outputs(
        {"state": state, "release_id": "" if draft_id is None else str(draft_id)}
    )


def run_check_archives(arguments: argparse.Namespace) -> None:
    """Verify one architecture's archives and the images loaded from them."""
    directory = Path(arguments.archives)
    for component in COMPONENTS:
        archive = read_archive(directory / f"{component}.tar")
        if archive.platform != f"linux/{arguments.arch}":
            raise ReleaseError(
                f"{archive.path} is {archive.platform}, expected linux/{arguments.arch}"
            )
        check_labels(
            archive.labels,
            expected_labels(
                component, arguments.repository, arguments.sha, arguments.version
            ),
            str(archive.path),
        )
        image = f"docksight-{component}:release-{arguments.arch}"
        result = subprocess.run(
            [
                shutil.which("docker") or "docker",
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                image,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        check_loaded(archive, result.stdout.strip())
        print(f"{image} is {archive.digest}")


def run_images(arguments: argparse.Namespace) -> None:
    """Publish both multi-platform images."""
    digests = publish_images(
        SkopeoRegistry(),
        Path(arguments.archives),
        arguments.namespace,
        arguments.repository,
        arguments.sha,
        arguments.version,
    )
    write_outputs(
        {f"{component}_digest": value for component, value in digests.items()}
    )


def run_release(arguments: argparse.Namespace) -> None:
    """Upload the assets and publish the release."""
    images = dict(item.split("=", 1) for item in arguments.image)
    if set(images) != set(COMPONENTS):
        raise ReleaseError(f"--image must name exactly {list(COMPONENTS)}")
    publish_release(
        github_api(),
        SkopeoRegistry(),
        arguments.repository,
        arguments.sha,
        arguments.version,
        arguments.release_id,
        Path(arguments.assets),
        images,
    )
    print(f"Published v{arguments.version}")


def parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--repository", required=True, help="owner/name")
    shared.add_argument("--sha", required=True, type=check_sha, help="Candidate commit")
    draft = commands.add_parser(
        "draft", parents=[shared], help="Create or resume the draft release"
    )
    draft.add_argument("--tag", required=True)
    draft.add_argument("--notes", required=True)
    draft.set_defaults(handler=run_draft)
    check = commands.add_parser(
        "check-archives", parents=[shared], help="Verify archives and loaded images"
    )
    check.add_argument("--version", required=True)
    check.add_argument("--arch", required=True, choices=ARCHES)
    check.add_argument("--archives", required=True)
    check.set_defaults(handler=run_check_archives)
    images = commands.add_parser(
        "images", parents=[shared], help="Publish the tested images"
    )
    images.add_argument("--version", required=True)
    images.add_argument("--namespace", required=True)
    images.add_argument("--archives", required=True)
    images.set_defaults(handler=run_images)
    release = commands.add_parser(
        "release", parents=[shared], help="Upload assets and publish the draft"
    )
    release.add_argument("--version", required=True)
    release.add_argument("--release-id", required=True, type=int)
    release.add_argument("--assets", required=True)
    release.add_argument(
        "--image", required=True, action="append", help="component=reference"
    )
    release.set_defaults(handler=run_release)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    """Run one publication command."""
    arguments = parser().parse_args(argv)
    try:
        arguments.handler(arguments)
    except (
        QualificationError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ) as error:
        print(f"Release publication failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
