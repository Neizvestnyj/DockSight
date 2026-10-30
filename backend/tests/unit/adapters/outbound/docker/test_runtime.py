from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from docker.errors import DockerException, NotFound
from paramiko import SSHException
from requests import RequestException

from docksight.adapters.outbound.docker.hosts import HostConfig
from docksight.adapters.outbound.docker.runtime import DockerRuntime
from docksight.application.redaction import Redactor
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import ContainerSnapshot
from tests.fakes import snapshot


async def test_ping_uses_a_short_timeout_and_closes_the_selected_connection() -> None:
    runtime = DockerRuntime((HostConfig(id="local"),), Redactor(()), timeout=15)
    sdk = MagicMock()
    sdk.api.ping.return_value = True
    with patch("docksight.adapters.outbound.docker.runtime.connect", return_value=sdk) as connect:
        await runtime.ping("local")
    assert connect.call_args.args[1] == 3
    sdk.api.ping.assert_called_once_with()
    sdk.api.containers.assert_not_called()
    sdk.close.assert_called_once()
    await runtime.close()


async def test_ping_rejects_unconfigured_hosts_and_false_engine_responses() -> None:
    runtime = DockerRuntime((HostConfig(id="local"),), Redactor(()))
    with pytest.raises(DockSightError, match="Configured host not found"):
        await runtime.ping("unknown")
    sdk = MagicMock()
    sdk.api.ping.return_value = False
    with patch("docksight.adapters.outbound.docker.runtime.connect", return_value=sdk):
        with pytest.raises(DockSightError, match="Docker ping failed"):
            await runtime.ping("local")
    await runtime.close()


@pytest.mark.parametrize(
    ("failure", "code", "status"),
    [
        (NotFound("missing"), "container_not_found", 404),
        (DockerException("disconnected"), "runtime_unavailable", 503),
        (RequestException("connection lost"), "runtime_unavailable", 503),
        (SSHException("connection lost"), "runtime_unavailable", 503),
        (OSError("socket closed"), "runtime_unavailable", 503),
    ],
)
async def test_failed_restart_translates_sdk_errors_without_retrying(
    failure: Exception, code: str, status: int
) -> None:
    runtime = DockerRuntime((HostConfig(id="local"),), Redactor(()))
    sdk = MagicMock()
    sdk.api.restart.side_effect = failure
    with patch("docksight.adapters.outbound.docker.runtime.connect", return_value=sdk):
        with pytest.raises(DockSightError) as caught:
            await runtime.restart("local", "a" * 64)
    assert (caught.value.code, caught.value.status) == (code, status)
    assert caught.value.__cause__ is failure
    sdk.api.restart.assert_called_once_with("a" * 64, timeout=10)
    sdk.close.assert_called_once()
    await runtime.close()


@pytest.mark.parametrize(("max_bytes", "truncated"), [(64, True), (256, False)])
async def test_logs_redact_environment_secrets_bound_output_and_close_stream(max_bytes: int, truncated: bool) -> None:
    runtime = DockerRuntime((HostConfig(id="local"),), Redactor(()))
    sdk = MagicMock()
    sdk.api.inspect_container.return_value = {"Config": {"Env": ["DB_PASSWORD=secret-value"]}}
    stream = sdk.api.logs.return_value

    def log_chunks() -> Iterator[bytes]:
        """Reject further stream consumption once the byte budget has been exceeded."""
        yield b"2026-01-01T00:00:00Z connected secret-value\n"
        yield b"x" * 64 + b"\n"
        if truncated:
            raise AssertionError("Log stream was read beyond the byte budget")

    stream.__iter__.return_value = log_chunks()
    with patch("docksight.adapters.outbound.docker.runtime.connect", return_value=sdk):
        result = await runtime.logs("local", "a" * 64, lines=2, max_bytes=max_bytes)
    assert result.truncated is truncated
    assert result.entries[0].message == "connected [REDACTED]"
    assert result.entries[0].timestamp is not None
    assert len(result.entries) == (1 if truncated else 2)
    sdk.api.logs.assert_called_once_with("a" * 64, tail=2, timestamps=True, stream=True, follow=False)
    stream.close.assert_called_once()
    sdk.close.assert_called_once()
    await runtime.close()


async def test_compose_groups_retain_each_member_state() -> None:
    from dataclasses import replace

    class InventoryRuntime(DockerRuntime):
        """Expose a small Docker inventory without opening a client."""

        async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
            """Return two failed members and an unrelated container."""
            item = replace(snapshot(), compose_project="infra")
            return item, replace(item, id="b" * 64, name="api"), replace(item, id="c" * 64, compose_project=None)

    runtime = InventoryRuntime((HostConfig(id="local"),), Redactor(()))
    groups = await runtime.stacks("local", "compose")
    assert len(groups) == 1
    assert groups[0].name == "infra"
    assert groups[0].total == 2
    assert [row.state for row in groups[0].members] == ["exited", "exited"]
    assert groups[0].members[1].exit_code == 1


async def test_swarm_stacks_group_services_by_namespace_and_keep_replica_counts() -> None:
    runtime = DockerRuntime((HostConfig(id="local"),), Redactor(()))
    sdk = MagicMock()
    sdk.api.info.return_value = {"Swarm": {"ControlAvailable": True}}
    sdk.api.services.return_value = [
        {
            "ID": "s1",
            "Spec": {
                "Name": "infra_api",
                "Labels": {"com.docker.stack.namespace": "infra"},
                "Mode": {"Replicated": {"Replicas": 2}},
            },
        },
        {
            "ID": "s2",
            "Spec": {
                "Name": "infra_worker",
                "Labels": {"com.docker.stack.namespace": "infra"},
                "Mode": {"Replicated": {"Replicas": 1}},
            },
        },
        {"ID": "s3", "Spec": {"Name": "standalone", "Labels": {}, "Mode": {"Replicated": {"Replicas": 1}}}},
    ]
    sdk.api.tasks.return_value = [{"Status": {"State": "running", "ContainerStatus": {"ContainerID": "a" * 64}}}]
    with patch("docksight.adapters.outbound.docker.runtime.connect", return_value=sdk):
        groups = await runtime.stacks("local", "swarm")
    assert len(groups) == 1
    assert (groups[0].name, groups[0].total, groups[0].running) == ("infra", 3, 2)
    assert [row.name for row in groups[0].members] == ["infra_api", "infra_worker"]
    assert groups[0].members[0].state == "degraded"
    assert groups[0].members[0].kind == "service"
    assert len(sdk.api.tasks.call_args_list) == 2
