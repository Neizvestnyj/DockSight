from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.integration.persistence import live


@pytest.mark.parametrize("ownership", ["owned", "id_changed", "label_changed"])
def test_metadata_write_failure_cleans_only_the_in_hand_owned_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ownership: str
) -> None:
    client, container = MagicMock(), MagicMock()
    identity = "a" * 64
    container.id, container.name = identity, "owned-fixture"
    client.containers.run.return_value = container
    client.containers.get.return_value = container

    def run(*args: object, **kwargs: object) -> MagicMock:
        """Retain the unique create label as the fixture's only cleanup authority."""
        container.labels = kwargs["labels"]
        return container

    def fail(self: Path, *args: object, **kwargs: object) -> int:
        """Fail metadata publication after creation and optionally change cleanup identity."""
        if ownership == "id_changed":
            container.id = "b" * 64
        elif ownership == "label_changed":
            container.labels = {live.LABEL: "foreign"}
        raise OSError("metadata unavailable")

    client.containers.run.side_effect = run
    monkeypatch.setattr(live.docker, "from_env", lambda **kwargs: client)
    monkeypatch.setattr(Path, "write_text", fail)
    with pytest.raises((OSError, AssertionError)):
        live.create(tmp_path)
    assert container.remove.call_count == (1 if ownership == "owned" else 0)
    if ownership == "owned":
        container.remove.assert_called_once_with(force=True)
    client.close.assert_called_once()


@pytest.mark.parametrize("failure", ["image", "container"])
def test_acquisition_failure_closes_client_without_removing_uncreated_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    client = MagicMock()
    dependency = client.images.get if failure == "image" else client.containers.run
    dependency.side_effect = RuntimeError("acquisition failed")
    monkeypatch.setattr(live.docker, "from_env", lambda **kwargs: client)
    with pytest.raises(RuntimeError, match="acquisition failed"):
        live.create(tmp_path)
    client.containers.get.assert_not_called()
    client.containers.run.return_value.remove.assert_not_called()
    client.close.assert_called_once()
