import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from docksight.application.ports.runtime import RuntimeReadPort
from docksight.application.views.schemas import GroupTarget
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import ContainerSnapshot


@dataclass(frozen=True)
class TargetResolution:
    """Retain discovery snapshots and an unambiguous named group for one turn."""

    group: GroupTarget | None
    containers: tuple[ContainerSnapshot, ...]
    discovery_code: str | None = None


def _mentioned(query: str, name: str) -> bool:
    """Match whole resource names, preserving punctuation without expanding container prefixes."""
    return re.search(r"(?<![\w.-])" + re.escape(name) + r"(?![\w-]|\.[\w-])", query, re.IGNORECASE) is not None


async def resolve_target(runtime: RuntimeReadPort, host: str, query: str) -> TargetResolution:
    """Prefer exact identities; tolerate one unambiguous edit in a long observed group name."""
    rows = await runtime.containers(host)
    if any(row.id in query for row in rows):
        return TargetResolution(None, rows)
    named_container = any(_mentioned(query, row.name) for row in rows)
    groups, code = await _group_candidates(runtime, host, rows, query, named_container)
    exact = [row for row in groups if _mentioned(query, row.name)]
    targets = exact or ([] if named_container else _near_groups(groups, query))
    return TargetResolution(_unambiguous_target(targets, bool(exact) and named_container), rows, code)


async def _group_candidates(
    runtime: RuntimeReadPort, host: str, rows: tuple[ContainerSnapshot, ...], query: str, named_container: bool
) -> tuple[list[GroupTarget], str | None]:
    """Read group identities in the requested namespaces without inferring membership from names."""
    kind = _requested_kind(query)
    names = sorted({row.compose_project for row in rows if row.compose_project})
    groups = _valid_targets(names, "compose") if kind != "swarm" else []
    code = None
    if kind != "compose" and (not named_container or any(_mentioned(query, row.name) for row in groups)):
        swarm, code = await _swarm_groups(runtime, host, kind == "swarm")
        groups.extend(swarm)
    return groups, code


def _valid_targets(names: Iterable[str], kind: Literal["compose", "swarm"]) -> list[GroupTarget]:
    """Exclude unrelated labels that cannot be selected through the public group contract."""
    targets: list[GroupTarget] = []
    for name in names:
        try:
            target = GroupTarget(kind=kind, name=name)
        except ValidationError:
            continue
        targets.append(target)
    return targets


def _near_groups(groups: list[GroupTarget], query: str) -> list[GroupTarget]:
    """Compare complete query tokens only, never arbitrary substrings or generated resource names."""
    tokens = re.findall(r"[\w.-]+", query.casefold())
    return [row for row in groups if any(_one_edit(token.rstrip("."), row.name.casefold()) for token in tokens)]


def _one_edit(left: str, right: str) -> bool:
    """Recognize one substitution, insertion, deletion, or adjacent transposition in names of six or more characters."""
    if min(len(left), len(right)) < 6 or abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    offset = next((index for index, pair in enumerate(zip(left, right, strict=False)) if pair[0] != pair[1]), len(left))
    a, b = left[offset:], right[offset:]
    if len(left) != len(right):
        return a == b[1:]
    return a[1:] == b[1:] or (len(a) > 1 and a[:2] == b[1::-1] and a[2:] == b[2:])


def _unambiguous_target(targets: list[GroupTarget], named_container: bool) -> GroupTarget | None:
    """Require explicit selection when observed identities collide across resource types."""
    if len(targets) > 1 or (targets and named_container):
        raise DockSightError("ambiguous_target", "Resource name is ambiguous; select one group or exact container", 422)
    return targets[0] if targets else None


def _requested_kind(query: str) -> Literal["compose", "swarm"] | None:
    """Respect explicit technology names without treating the generic word stack as Swarm."""
    if re.search(r"\bcompose\b", query, re.IGNORECASE):
        return "compose"
    if re.search(r"\bswarm\b", query, re.IGNORECASE):
        return "swarm"
    return None


async def _swarm_groups(runtime: RuntimeReadPort, host: str, required: bool) -> tuple[list[GroupTarget], str | None]:
    """Discover manager-owned stack names, retaining optional discovery failures separately."""
    try:
        stacks = await runtime.stacks(host, "swarm")
    except DockSightError as exc:
        if required:
            raise
        return [], None if exc.code == "unsupported_operation" else exc.code
    return _valid_targets((row.name for row in stacks if row.kind == "swarm"), "swarm"), None
