import json
import re
from dataclasses import dataclass
from hashlib import sha256
from heapq import nsmallest
from operator import attrgetter
from typing import Annotated, Final

from pydantic import ConfigDict, Field, computed_field

from docksight.application.views.schemas import Contract, GroupTarget
from docksight.domain.errors import DockSightError, ErrorKind
from docksight.domain.runtime import ContainerState

SEARCH_QUERY_LENGTH: Final = 128
SEARCH_PAGE_SIZE: Final = 50
SEARCH_CURSOR_LENGTH: Final = 129
_CONTAINER_ID: Final = re.compile(r"[a-f0-9]{64}")

type ContainerName = Annotated[str, Field(min_length=1, max_length=1024)]


class ContainerSummary(Contract):
    """Expose allowlisted metadata from one Docker list entry."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed_name: ContainerName | None = Field(default=None, exclude=True)
    image: str = Field(max_length=1024)
    state: ContainerState
    compose_project: str | None = Field(default=None, max_length=1024)
    swarm_stack: str | None = Field(default=None, max_length=1024)

    @computed_field
    @property
    def name(self) -> ContainerName:
        """Display the stable ID when Docker reports an unnamed container."""
        return self.observed_name or self.id


class ContainerSearchPage(Contract):
    """Return only a bounded page of matching container summaries."""

    items: tuple[ContainerSummary, ...] = Field(max_length=SEARCH_PAGE_SIZE)
    next_cursor: str | None = Field(default=None, max_length=SEARCH_CURSOR_LENGTH)


@dataclass(frozen=True)
class ContainerSearch:
    """Carry the submitted query, page coordinates, and optional exact group scope."""

    query: str
    limit: int = 20
    before: str | None = None
    group: GroupTarget | None = None

    def prepare(self, host: str) -> "PreparedContainerSearch":
        """Validate page coordinates and bind them to the effective query before contacting Docker."""
        query = self.query.strip().casefold()
        if not query or len(self.query) > SEARCH_QUERY_LENGTH or not 1 <= self.limit <= SEARCH_PAGE_SIZE:
            raise DockSightError("invalid_container_search", "Invalid search query or page limit", ErrorKind.VALIDATION)

        group = self.group.model_dump() if self.group else None
        digest = sha256(json.dumps([host, query, group], separators=(",", ":")).encode()).hexdigest()
        after_id = _decode_cursor(self.before, digest)
        return PreparedContainerSearch(query, self.limit, self.group, digest, after_id)


def _decode_cursor(before: str | None, digest: str) -> str:
    """Return the pivot identity of a cursor scoped to this host and query."""
    if before is None:
        return ""
    scope, _, identity = before.partition(".")
    if scope != digest or not _CONTAINER_ID.fullmatch(identity):
        raise DockSightError("invalid_cursor", "Invalid container search cursor", ErrorKind.VALIDATION)
    return identity


@dataclass(frozen=True)
class PreparedContainerSearch:
    """Apply validated literal matching and stable full-ID pagination to public metadata."""

    query: str
    limit: int
    group: GroupTarget | None
    digest: str
    after_id: str

    def matches(self, row: ContainerSummary) -> bool:
        """Match only the exact group scope and a sanitized name, image, project, or ID prefix."""
        if self.group:
            group_name = row.compose_project if self.group.kind == "compose" else row.swarm_stack
            if group_name != self.group.name:
                return False
        return row.id.startswith(self.query) or any(
            self.query in text.casefold() for text in (row.observed_name or "", row.image, row.compose_project or "")
        )

    def page(self, rows: tuple[ContainerSummary, ...]) -> ContainerSearchPage:
        """Select the next matching IDs without sorting or returning the entire inventory."""
        candidates = (row for row in rows if row.id > self.after_id and self.matches(row))
        selected = nsmallest(self.limit + 1, candidates, key=attrgetter("id"))
        items = tuple(selected[: self.limit])
        cursor = f"{self.digest}.{items[-1].id}" if len(selected) > self.limit else None
        return ContainerSearchPage(items=items, next_cursor=cursor)
