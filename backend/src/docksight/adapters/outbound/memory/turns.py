from datetime import datetime

from docksight.adapters.outbound.memory.investigations import MemoryInvestigations, MemoryTurn
from docksight.adapters.outbound.persistence.codec import utc_text
from docksight.application.investigations.contracts import (
    AcceptedTurn,
    ClarificationTurn,
    SavedTurn,
    StartTurn,
    TurnOutcome,
    TurnUpdate,
)
from docksight.application.investigations.errors import HistoryError, capacity
from docksight.application.investigations.lifecycle import (
    accepted_snapshot,
    accepted_workspace,
    append_context,
    conflict,
    finished_snapshot,
    updated_snapshot,
)
from docksight.application.ports.models import ModelMessage
from docksight.domain.errors import ErrorKind


class MemoryTurnStore:
    """Apply atomic detached turn transitions to the explicit development archive."""

    def __init__(self, archive: MemoryInvestigations) -> None:
        """Share archive ownership, quotas, receipts, and scope with browsing operations."""
        self.archive = archive

    async def submission(self, actor: str, submission_id: str, input_digest: str) -> SavedTurn | None:
        """Resolve a prior receipt without inspecting mutable configuration or admission state."""
        receipt = self.archive.history.receipts.get((actor, submission_id))
        if receipt is None:
            return None
        digest, identity, deleted = receipt
        if digest != input_digest:
            raise conflict("submission_conflict", "Submission already exists for different input")
        if deleted:
            raise HistoryError("history_deleted", "Saved history was explicitly deleted", ErrorKind.NOT_FOUND)
        return await self.archive.read_turn(actor, identity)

    async def accept(
        self, actor: str, command: StartTurn, input_digest: str, request_id: str, now: datetime
    ) -> AcceptedTurn:
        """Recheck duplicate receipts and reserve the maximum snapshot allowance before any work."""
        existing = await self.submission(actor, command.root.submission_id, input_digest)
        if existing is not None:
            return AcceptedTurn(snapshot=existing, created=False)
        archive = self.archive
        view = archive.owned(actor, command.root.investigation_id)
        if (actor, view.host) in archive.history.scopes:
            raise conflict("turn_busy", "A diagnostic turn is already running on this host")
        parent = None
        if isinstance(command.root, ClarificationTurn):
            parent = await archive.read_turn(actor, command.root.clarification_of)
        saved = accepted_snapshot(actor, view.host, command, view.workspace, parent, request_id, now)
        if view.turn_count >= archive.limits.turns_per_investigation:
            raise capacity()
        workspace = accepted_workspace(view.workspace, saved)
        amendments = {saved.id: self._encoded(saved)}
        if parent is not None:
            parent = parent.model_copy(
                update={"resolved_by_turn_id": saved.id, "revision": parent.revision + 1, "updated_at": now}
            )
            amendments[parent.id] = self._encoded(parent)
        remaining = archive.limits.snapshot_bytes - len(amendments[saved.id].snapshot.encode())
        archive.check_capacity(actor, view.id, workspace, turns=archive.history.turns | amendments, reserved=remaining)
        archive.history.reserved[view.id] = remaining
        archive.history.investigations[view.id] = view.model_copy(
            update={
                "workspace": workspace,
                "active_turn_id": saved.id,
                "title": view.title or saved.query[:120],
                "updated_at": now,
            }
        )
        archive.history.turns.update(amendments)
        archive.history.scopes[actor, view.host] = saved.id
        archive.history.receipts[actor, saved.submission_id] = input_digest, saved.id, False
        prefs = await archive.workspace(actor)
        archive.history.workspaces[actor] = prefs.model_copy(
            update={
                "revision": prefs.revision + 1,
                "last_investigation_id": view.id,
                "host": view.host,
                "model": saved.model,
            }
        )
        return AcceptedTurn(snapshot=saved.model_copy(deep=True), created=True)

    def _save(self, saved: SavedTurn) -> None:
        """Encode snapshots so callers cannot mutate retained cards, traces, or selections."""
        self.archive.history.turns[saved.id] = self._encoded(saved)

    def _encoded(self, saved: SavedTurn) -> MemoryTurn:
        """Validate the snapshot limit before changing any retained in-memory state."""
        encoded = saved.model_dump_json()
        if len(encoded.encode()) > self.archive.limits.snapshot_bytes:
            raise capacity()
        return MemoryTurn(saved.investigation_id, utc_text(saved.created_at), encoded, saved.state)

    async def update(self, actor: str, turn_id: str, update: TurnUpdate, now: datetime) -> SavedTurn:
        """Commit safe progress only while the actor-owned turn and revision remain active."""
        current = await self.archive.read_turn(actor, turn_id)
        saved = updated_snapshot(current, update, now)
        self._save(saved)
        self.archive.history.reserved[saved.investigation_id] = self.archive.limits.snapshot_bytes - len(
            saved.model_dump_json().encode()
        )
        return saved.model_copy(deep=True)

    async def finish(self, actor: str, turn_id: str, outcome: TurnOutcome, now: datetime) -> SavedTurn:
        """Commit terminal content, bounded context, and released active scope together."""
        current = await self.archive.read_turn(actor, turn_id)
        saved = finished_snapshot(current, outcome, now)
        archive = self.archive
        context = append_context(archive.history.contexts.get(saved.investigation_id, ()), saved)
        amendments = {saved.id: self._encoded(saved)}
        view = archive.owned(actor, saved.investigation_id)
        archive.check_capacity(
            actor, view.id, view.workspace, turns=archive.history.turns | amendments, context=context, reserved=0
        )
        archive.history.turns.update(amendments)
        archive.history.contexts[saved.investigation_id] = context
        archive.history.reserved.pop(saved.investigation_id, None)
        archive.history.scopes.pop((actor, saved.host), None)
        archive.history.investigations[view.id] = view.model_copy(update={"active_turn_id": None, "updated_at": now})
        return saved.model_copy(deep=True)

    async def context(self, actor: str, investigation_id: str) -> tuple[ModelMessage, ...]:
        """Return only plain bounded history after archive ownership has been checked."""
        self.archive.owned(actor, investigation_id)
        return self.archive.history.contexts.get(investigation_id, ())
