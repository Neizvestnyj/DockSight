from collections.abc import Callable, Set
from datetime import UTC, datetime

from docksight.application.investigations.contracts import (
    ActorWorkspace,
    ActorWorkspacePatch,
    InvestigationPage,
    InvestigationView,
    InvestigationWorkspace,
    TurnPage,
    WorkspacePatch,
)
from docksight.application.investigations.ports import InvestigationArchive
from docksight.application.redaction import Redactor
from docksight.domain.errors import DockSightError, ErrorKind


class Investigations:
    """Validate configured scope and sanitize acknowledged actor-owned archive changes."""

    def __init__(self, archive: InvestigationArchive, hosts: Callable[[], Set[str]], redactor: Redactor) -> None:
        """Resolve configured host identities without retaining transport or settings objects."""
        self.archive, self.hosts, self.redactor = archive, hosts, redactor

    def validate_host(self, host: str) -> None:
        """Reject arbitrary or removed host identities before accepting new work."""
        if host not in self.hosts():
            raise DockSightError("host_not_found", "Configured host not found", ErrorKind.NOT_FOUND)

    async def create(self, actor: str, investigation_id: str, host: str) -> InvestigationView:
        """Create an empty configured-host archive without starting diagnostic work."""
        self.validate_host(host)
        return await self.archive.create(actor, investigation_id, host, datetime.now(UTC))

    async def list_owned(self, actor: str, limit: int = 10, cursor: str | None = None) -> InvestigationPage:
        """Read bounded owned activity without refreshing models or runtime data."""
        return await self.archive.list_owned(actor, limit, cursor)

    async def read(self, actor: str, investigation_id: str) -> InvestigationView:
        """Read saved content even when its former host configuration was removed."""
        return await self.archive.read(actor, investigation_id)

    async def turns(self, actor: str, investigation_id: str, limit: int = 20, cursor: str | None = None) -> TurnPage:
        """Page complete owned display history independently of bounded model context."""
        return await self.archive.turns(actor, investigation_id, limit, cursor)

    async def workspace(self, actor: str) -> ActorWorkspace:
        """Read independently revisioned actor preferences."""
        return await self.archive.workspace(actor)

    async def patch_workspace(self, actor: str, investigation_id: str, patch: WorkspacePatch) -> InvestigationWorkspace:
        """Sanitize draft text while retaining explicit-field and optimistic revision semantics."""
        if "draft" in patch.model_fields_set:
            patch = patch.model_copy(update={"draft": self.redactor.text(patch.draft)})
        return await self.archive.patch_workspace(actor, investigation_id, patch, datetime.now(UTC))

    async def patch_actor_workspace(self, actor: str, patch: ActorWorkspacePatch) -> ActorWorkspace:
        """Validate explicit host preferences without overwriting investigation drafts."""
        if patch.host is not None:
            self.validate_host(patch.host)
        return await self.archive.patch_actor_workspace(actor, patch, datetime.now(UTC))

    async def delete(self, actor: str, investigation_id: str) -> None:
        """Explicitly remove owned inactive history while retaining submission tombstones."""
        await self.archive.delete(actor, investigation_id, datetime.now(UTC))
