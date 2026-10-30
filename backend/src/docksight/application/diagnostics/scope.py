import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from docksight.application.ports.runtime import RuntimeReadPort
from docksight.application.views.schemas import GroupSelection, GroupTarget
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import ContainerSnapshot


@dataclass(frozen=True)
class TargetResolution:
    """Retain discovery snapshots and an unambiguous named group for one turn."""

    group: GroupTarget | None
    containers: tuple[ContainerSnapshot, ...]
    discovery_code: str | None = None
    candidates: tuple[GroupTarget, ...] = ()
    selection: GroupSelection | None = None
    container_id: str | None = None


def _mentioned(query: str, name: str) -> bool:
    """Match whole resource names, preserving punctuation without expanding container prefixes."""
    return re.search(r"(?<![\w.-])" + re.escape(name) + r"(?![\w-]|\.[\w-])", query, re.IGNORECASE) is not None


def _container_reference(query: str, name: str) -> bool:
    """Honor an explicitly typed exact container name without interpreting an unqualified name collision."""
    prefix = r"\b(?:container|контейнер(?:а|у|ом|е|ы|ов)?)\s+(?:(?:named|called|\u0441 именем)\s+)?[\"'`«]?"  # noqa: RUF001
    return re.search(prefix + re.escape(name) + r"(?![\w-]|\.[\w-])", query, re.IGNORECASE) is not None


def _container_target(query: str, rows: tuple[ContainerSnapshot, ...]) -> TargetResolution | None:
    """Bind one explicit container, while leaving intentionally multi-container questions unrestricted."""
    ids = [row.id for row in rows if row.id in query or _container_reference(query, row.name)]
    return TargetResolution(None, rows, container_id=ids[0] if len(ids) == 1 else None) if ids else None


async def resolve_target(runtime: RuntimeReadPort, host: str, query: str) -> TargetResolution:
    """Prefer observed identities, space-separated spelling, or one unambiguous edit in a long group name."""
    rows = await runtime.containers(host)
    container = _container_target(query, rows)
    if container:
        return container
    named_container = any(_mentioned(query, row.name) for row in rows)
    groups, code = await _group_candidates(runtime, host, rows, query, named_container)
    targets, exact = _question_targets(groups, query, named_container)
    group = _unambiguous_target(targets, exact and named_container)
    selection = GroupSelection(candidates=targets[:32]) if len(targets) > 1 else None
    return TargetResolution(group, rows, code, tuple(groups), selection)


def _question_targets(groups: list[GroupTarget], query: str, named_container: bool) -> tuple[list[GroupTarget], bool]:
    """Distinguish explicit group references from typo matches and unscoped incident alternatives."""
    exact = [row for row in groups if _mentioned(query, row.name) or _mentioned(query, row.name.replace("-", " "))]
    if exact:
        return exact, True
    targets = [] if named_container else _near_groups(groups, query)
    if not targets and not named_container and _unscoped_incident(query):
        targets = groups if len(groups) > 1 else []
    return targets, False


def _unscoped_incident(query: str) -> bool:
    """Recognize bare incident questions without treating named or descriptive resource requests as host-wide."""
    text = " ".join(re.findall(r"[\w']+", query.casefold().replace("\u2019", "'")))
    return (
        re.fullmatch(
            r"(?:(?:\u0430 )?что (?:случилось|произошло|упало|сломалось|не так)(?: \u0443 нас)?|"
            r"what (?:happened|failed|broke|is down|is wrong|went wrong)|what's (?:wrong|down|broken))",
            text,
        )
        is not None
    )


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


def group_alternatives(target: GroupTarget, candidates: tuple[GroupTarget, ...], query: str) -> GroupSelection | None:
    """Require an exact choice before an inferred target can bypass a nearly identical observed identity."""
    if _mentioned(query, target.name):
        return None
    neighbors = [row for row in candidates if row.name == target.name or _one_edit(row.name, target.name)]
    return GroupSelection(candidates=neighbors[:32]) if target in neighbors and len(neighbors) > 1 else None


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
    if targets and named_container:
        raise DockSightError("ambiguous_target", "Resource name is ambiguous; select one group or exact container", 422)
    return targets[0] if len(targets) == 1 else None


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
