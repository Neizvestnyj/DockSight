from pathlib import Path

import pytest

from docksight.adapters.outbound.docker.hosts import load_hosts
from docksight.domain.errors import DockSightError


@pytest.mark.parametrize("url", ["tcp://example:2375", "http://example", "ssh://-bad", "ssh://user:password@host"])
def test_unsafe_host_connections_are_rejected(tmp_path: Path, url: str) -> None:
    """Verify unsafe host connections are rejected."""
    path = tmp_path / "hosts.yaml"
    path.write_text(f"hosts:\n  - id: remote\n    url: {url}\n", encoding="utf-8")
    with pytest.raises(DockSightError):
        load_hosts(str(path))


def test_duplicate_host_ids_are_rejected(tmp_path: Path) -> None:
    """Verify duplicate host ids are rejected."""
    path = tmp_path / "hosts.yaml"
    path.write_text("hosts:\n  - id: local\n  - id: local\n", encoding="utf-8")
    with pytest.raises(DockSightError):
        load_hosts(str(path))
