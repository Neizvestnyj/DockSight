from unittest.mock import MagicMock, patch

import pytest

from docksight.adapters.outbound.docker.hosts import HostConfig
from docksight.adapters.outbound.docker.runtime import DockerRuntime
from docksight.application.redaction import Redactor
from docksight.domain.errors import DockSightError


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
