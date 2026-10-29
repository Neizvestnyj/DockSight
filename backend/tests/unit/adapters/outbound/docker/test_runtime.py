from unittest.mock import MagicMock, patch

import pytest

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
