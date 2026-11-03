from unittest.mock import MagicMock, patch

import pytest
from docker.errors import DockerException, NotFound
from paramiko import SSHException
from requests import RequestException

from docksight.adapters.outbound.docker.hosts import HostConfig
from docksight.adapters.outbound.docker.runtime import DockerRuntime
from docksight.application.redaction import Redactor
from docksight.domain.errors import DockSightError, ErrorKind
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
    ("failure", "code", "kind"),
    [
        (NotFound("missing"), "container_not_found", ErrorKind.NOT_FOUND),
        (DockerException("disconnected"), "runtime_unavailable", ErrorKind.UNAVAILABLE),
        (RequestException("connection lost"), "runtime_unavailable", ErrorKind.UNAVAILABLE),
        (SSHException("connection lost"), "runtime_unavailable", ErrorKind.UNAVAILABLE),
        (OSError("socket closed"), "runtime_unavailable", ErrorKind.UNAVAILABLE),
    ],
)
async def test_failed_restart_translates_sdk_errors_without_retrying(
    failure: Exception, code: str, kind: ErrorKind
) -> None:
    runtime = DockerRuntime((HostConfig(id="local"),), Redactor(()))
    sdk = MagicMock()
    sdk.api.restart.side_effect = failure
    with patch("docksight.adapters.outbound.docker.runtime.connect", return_value=sdk):
        with pytest.raises(DockSightError) as caught:
            await runtime.restart("local", "a" * 64)
    assert (caught.value.code, caught.value.kind) == (code, kind)
    assert caught.value.__cause__ is failure
    sdk.api.restart.assert_called_once_with("a" * 64, timeout=10)
    sdk.close.assert_called_once()
    await runtime.close()


@pytest.mark.parametrize(("max_bytes", "truncated"), [(64, True), (256, False)])
async def test_logs_redact_environment_secrets_and_bound_output(max_bytes: int, truncated: bool) -> None:
    runtime = DockerRuntime((HostConfig(id="local"),), Redactor(()))
    sdk = MagicMock()
    sdk.api.inspect_container.return_value = {"Config": {"Env": ["DB_PASSWORD=secret-value"]}}
    chunks = (
        b"2026-01-01T00:00:00Z connected secret-value\n"
        + b"x" * 64
        + b"\n2026-01-01T00:00:01Z database system is shut down\n"
    )
    with (
        patch("docksight.adapters.outbound.docker.runtime.connect", return_value=sdk),
        patch("docksight.adapters.outbound.docker.runtime.read_logs", return_value=chunks),
    ):
        result = await runtime.logs("local", "a" * 64, lines=3, max_bytes=max_bytes)
    assert result.truncated is truncated
    assert result.entries[-1].message == "database system is shut down"
    assert result.entries[-1].timestamp is not None
    if not truncated:
        assert result.entries[0].message == "connected [REDACTED]"
    assert len(result.entries) == (1 if truncated else 3)
    sdk.close.assert_called_once()
    await runtime.close()


async def test_compose_groups_retain_each_member_state() -> None:
    from dataclasses import replace

    class InventoryRuntime(DockerRuntime):
        """Expose a small Docker inventory without opening a client."""

        async def containers(self, host: str) -> tuple[ContainerSnapshot, ...]:
            """Return two failed members and an unrelated container."""
            item = replace(snapshot(), compose_project="infra", state="running", health="unhealthy", exit_code=0)
            return (
                item,
                replace(item, id="b" * 64, name="api", state="exited", health=None, exit_code=1),
                replace(item, id="c" * 64, compose_project=None),
            )

    runtime = InventoryRuntime((HostConfig(id="local"),), Redactor(()))
    groups = await runtime.stacks("local", "compose")
    assert len(groups) == 1
    assert groups[0].name == "infra"
    assert groups[0].total == 2
    assert groups[0].running == 1
    assert [row.state for row in groups[0].members] == ["running", "exited"]
    assert [row.health for row in groups[0].members] == ["unhealthy", None]
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
