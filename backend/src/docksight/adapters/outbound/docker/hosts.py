from pathlib import Path
from typing import Self
from urllib.parse import ParseResult, urlparse

import docker
import yaml
from docker import DockerClient
from docker.tls import TLSConfig
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from docksight.domain.errors import DockSightError


class HostConfig(BaseModel):
    """Describe an operator-configured Docker endpoint and optional mTLS files."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str = Field(default="", max_length=100)
    url: str | None = None
    ca_cert: str | None = None
    client_cert: str | None = None
    client_key: str | None = None

    @model_validator(mode="after")
    def secure_transport(self) -> Self:
        """Reject unsupported or insecure Docker connection settings."""
        if self.url is None:
            return self
        parsed = urlparse(self.url)
        if parsed.scheme not in {"unix", "npipe", "ssh", "tcp"}:
            raise ValueError("Unsupported Docker transport")
        if parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Credentials and query parameters are not allowed in host URLs")
        if parsed.scheme in {"ssh", "tcp"}:
            _validate_remote_url(parsed)
        if parsed.scheme == "tcp" and not all((self.ca_cert, self.client_cert, self.client_key)):
            raise ValueError("TCP connections require mTLS certificates")

        return self


def _validate_remote_url(parsed: ParseResult) -> None:
    """Reject unsafe remote hostnames and paths before constructing an SDK client."""
    if not parsed.hostname or parsed.hostname.startswith("-"):
        raise ValueError("Invalid Docker hostname")
    if parsed.path not in {"", "/"}:
        raise ValueError("Remote Docker URLs cannot contain a path")


class HostsFile(BaseModel):
    """Validate a bounded collection of configured Docker hosts."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    hosts: list[HostConfig] = Field(min_length=1, max_length=32)


def load_hosts(path: str | None) -> tuple[HostConfig, ...]:
    """Load unique host definitions from bounded YAML or use the local Docker context."""
    if path is None:
        return (HostConfig(id="local", name="Local Docker"),)
    try:
        file = Path(path)
        if file.stat().st_size > 65536:
            raise ValueError("Host configuration exceeds 64 KiB")
        config = HostsFile.model_validate(yaml.safe_load(file.read_text(encoding="utf-8")))
        ids = [host.id for host in config.hosts]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate host IDs")
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as exc:
        raise DockSightError("invalid_hosts", "Invalid Docker host configuration", 500) from exc

    return tuple(config.hosts)


def connect(host: HostConfig, timeout: float) -> DockerClient:
    """Create an SDK client with verified SSH or mTLS for remote hosts."""
    if host.url is None:
        client = docker.from_env(timeout=max(1, int(timeout)))
        if client.api.base_url.startswith("http://"):
            client.close()
            raise DockSightError("insecure_transport", "Docker TCP connections require mTLS", 500)

        return client
    tls: bool | TLSConfig = False
    if host.url.startswith("tcp://"):
        assert host.client_cert and host.client_key and host.ca_cert
        tls = TLSConfig(
            client_cert=(host.client_cert, host.client_key),
            ca_cert=host.ca_cert,
            verify=True,
        )

    return DockerClient(base_url=host.url, tls=tls, timeout=max(1, int(timeout)), use_ssh_client=False)
