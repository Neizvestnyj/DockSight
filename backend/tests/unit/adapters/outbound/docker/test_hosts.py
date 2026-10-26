from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docksight.adapters.outbound.docker.hosts import HostConfig, connect, load_hosts
from docksight.domain.errors import DockSightError


@pytest.mark.parametrize("url", ["tcp://example:2375", "http://example", "ssh://-bad", "ssh://user:password@host"])
def test_unsafe_host_connections_are_rejected(tmp_path: Path, url: str) -> None:
    path = tmp_path / "hosts.yaml"
    path.write_text(f"hosts:\n  - id: remote\n    url: {url}\n", encoding="utf-8")
    with pytest.raises(DockSightError):
        load_hosts(str(path))


@pytest.mark.parametrize("environment_host", [False, True])
def test_ssh_connector_bounds_handshake_and_keeps_verified_config(tmp_path: Path, environment_host: bool) -> None:
    config = tmp_path / "config"
    config.write_text(
        "Host alias\n  HostName actual.example\n  User deploy\n  Port 2222\n"
        "  IdentityFile docker-key\n  ProxyCommand jump-proxy %h %p\n",
        encoding="utf-8",
    )
    with (
        patch("docker.transport.sshconn.os.path.expanduser", return_value=str(config)),
        patch("docker.transport.sshconn.paramiko.SSHClient") as client_type,
        patch("docker.transport.sshconn.paramiko.ProxyCommand") as proxy_type,
        patch("docker.api.client.APIClient._retrieve_server_version", return_value="1.47"),
        patch("docker.api.client.APIClient.version", return_value={"ApiVersion": "1.47"}),
        patch.dict("os.environ", {"DOCKER_HOST": "ssh://alias", "USERNAME": "operator"}, clear=True),
    ):
        client_type.return_value = MagicMock()
        host = HostConfig(id="remote", url=None if environment_host else "ssh://alias")
        engine = connect(host, 2.5)
        try:
            args = client_type.return_value.connect.call_args.kwargs
            expected_timeout = 2 if environment_host else 2.5
            assert args["timeout"] == expected_timeout
            assert args["banner_timeout"] == expected_timeout
            assert args["auth_timeout"] == expected_timeout
            assert args["channel_timeout"] == expected_timeout
            assert args["hostname"] == "actual.example"
            assert args["username"] == "deploy"
            assert str(args["port"]) == "2222"
            assert args["key_filename"] == ["docker-key"]
            assert args["sock"] is proxy_type.return_value
            client_type.return_value.load_system_host_keys.assert_called_once()
            policy = client_type.return_value.set_missing_host_key_policy.call_args.args[0]
            assert type(policy).__name__ == "RejectPolicy"
            assert engine.api.api_version == "1.47"
        finally:
            engine.close()


def test_duplicate_host_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "hosts.yaml"
    path.write_text("hosts:\n  - id: local\n  - id: local\n", encoding="utf-8")
    with pytest.raises(DockSightError):
        load_hosts(str(path))


@pytest.mark.parametrize("transport_started", [False, True])
def test_ssh_failure_closes_the_paramiko_client_and_proxy(tmp_path: Path, transport_started: bool) -> None:
    config = tmp_path / "config"
    config.write_text("Host alias\n  ProxyCommand jump-proxy %h %p\n", encoding="utf-8")
    with (
        patch("docker.transport.sshconn.os.path.expanduser", return_value=str(config)),
        patch("docker.transport.sshconn.paramiko.SSHClient") as client_type,
        patch("docker.transport.sshconn.paramiko.ProxyCommand", autospec=True) as proxy_type,
    ):
        client_type.return_value.connect.side_effect = TimeoutError("Handshake timed out")
        client_type.return_value.get_transport.return_value = object() if transport_started else None
        if transport_started:
            client_type.return_value.close.side_effect = proxy_type.return_value.close
        with pytest.raises(TimeoutError):
            connect(HostConfig(id="remote", url="ssh://alias"), 2.5)
        client_type.return_value.close.assert_called_once()
        proxy_type.return_value.close.assert_called_once()
