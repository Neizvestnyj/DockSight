from typing import Any, Protocol

from docksight.application.redaction import Redactor
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import ContainerSnapshot, StackMember, StackSummary


class SwarmAPI(Protocol):
    """Describe manager reads needed to summarize stack services and tasks."""

    def info(self) -> dict[str, Any]:
        """Read engine capabilities."""
        ...

    def services(self) -> list[dict[str, Any]]:
        """Read services visible to this manager."""
        ...

    def tasks(self, *, filters: dict[str, str]) -> list[dict[str, Any]]:
        """Read tasks within the selected service."""
        ...


def compose_stacks(containers: tuple[ContainerSnapshot, ...]) -> tuple[StackSummary, ...]:
    """Keep all observed project members, including failed and completed containers."""
    groups: dict[str, list[ContainerSnapshot]] = {}
    for row in containers:
        if row.compose_project:
            groups.setdefault(row.compose_project, []).append(row)
    return tuple(
        StackSummary(
            name,
            "compose",
            len(rows),
            sum(row.state == "running" for row in rows),
            tuple(row.id for row in rows),
            tuple(
                StackMember(row.id, row.name, "container", row.state, 1, int(row.state == "running"), row.exit_code)
                for row in rows
            ),
            len(containers) >= 200,
        )
        for name, rows in groups.items()
    )


def _service(
    client: SwarmAPI, service: dict[str, Any], redactor: Redactor
) -> tuple[StackMember, tuple[str, ...], bool]:
    """Summarize desired tasks without treating remote task containers as local observations."""
    spec: dict[str, Any] = service["Spec"]
    raw = client.tasks(filters={"service": service["ID"], "desired-state": "running"})
    tasks = raw[:200]
    mode: dict[str, Any] = spec.get("Mode") or {}
    replicated: dict[str, Any] = mode.get("Replicated") or {}
    total = int(replicated.get("Replicas", len(tasks)))
    running = sum(task.get("Status", {}).get("State") == "running" for task in tasks)
    ids = tuple(
        task["Status"]["ContainerStatus"]["ContainerID"]
        for task in tasks
        if task.get("Status", {}).get("ContainerStatus", {}).get("ContainerID")
    )
    member = StackMember(
        service["ID"],
        redactor.text(spec["Name"]),
        "service",
        "running" if running == total else "degraded",
        total,
        running,
    )
    return member, ids, len(raw) > 200


def swarm_stacks(client: SwarmAPI, redactor: Redactor) -> tuple[StackSummary, ...]:
    """Group namespace-labeled services into actual Swarm stacks, excluding standalone services."""
    swarm: dict[str, Any] = client.info().get("Swarm") or {}
    if not swarm.get("ControlAvailable"):
        raise DockSightError("unsupported_operation", "Swarm reads require a manager", 409)
    services = client.services()
    groups: dict[str, list[tuple[StackMember, tuple[str, ...], bool]]] = {}
    for service in services[:200]:
        labels: dict[str, str] = service["Spec"].get("Labels") or {}
        namespace = labels.get("com.docker.stack.namespace")
        if namespace:
            groups.setdefault(redactor.text(namespace), []).append(_service(client, service, redactor))
    return tuple(_stack_summary(name, rows, len(services) > 200) for name, rows in groups.items())


def _stack_summary(name: str, rows: list[tuple[StackMember, tuple[str, ...], bool]], truncated: bool) -> StackSummary:
    """Aggregate service task counts while preserving member observations and read limits."""
    container_ids = tuple(dict.fromkeys(cid for row in rows for cid in row[1]))
    return StackSummary(
        name,
        "swarm",
        sum(row[0].total for row in rows),
        sum(row[0].running for row in rows),
        container_ids[:200],
        tuple(row[0] for row in rows),
        truncated or any(row[2] for row in rows) or len(container_ids) > 200,
    )
