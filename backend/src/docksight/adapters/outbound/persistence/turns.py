import json
from datetime import datetime

from pydantic import TypeAdapter
from sqlalchemy import delete
from sqlalchemy.orm import Session

from docksight.adapters.outbound.persistence.codec import decode_turn, decode_value, utc_text
from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.adapters.outbound.persistence.investigations import (
    SQLiteInvestigations,
    actor_workspace,
    archive_view,
    owned,
    save_actor_workspace,
)
from docksight.adapters.outbound.persistence.rows import (
    ActiveTurnScopeRow,
    InvestigationRow,
    SubmissionReceiptRow,
    TurnRow,
)
from docksight.application.investigations.contracts import (
    AcceptedTurn,
    ClarificationTurn,
    InvestigationWorkspace,
    SavedTurn,
    StartTurn,
    StorageLimits,
    TurnOutcome,
    TurnUpdate,
)
from docksight.application.investigations.errors import HistoryError, capacity, not_found
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


def context_json(context: tuple[ModelMessage, ...]) -> str:
    """Serialize only application-owned plain bounded messages."""
    return json.dumps(
        [{"role": row.role, "content": row.content} for row in context], ensure_ascii=False, separators=(",", ":")
    )


def _submission(session: Session, actor: str, submission_id: str, digest: str) -> SavedTurn | None:
    """Resolve receipts before any mutable state or capacity checks inside the transaction."""
    receipt = session.get(SubmissionReceiptRow, (actor, submission_id))
    if receipt is None:
        return None
    if receipt.input_digest != digest:
        raise conflict("submission_conflict", "Submission already exists for different input")
    if receipt.archive_deleted_at is not None:
        raise HistoryError("history_deleted", "Saved history was explicitly deleted", ErrorKind.NOT_FOUND)
    return owned_turn(session, actor, receipt.turn_id)[1]


def owned_turn(session: Session, actor: str, identity: str) -> tuple[TurnRow, SavedTurn]:
    """Resolve owned indexed identity and return an independently validated snapshot."""
    row = session.get(TurnRow, identity)
    if row is None or row.actor != actor:
        raise not_found()
    owned(session, actor, row.investigation_id)
    saved = decode_turn(row.snapshot)
    if (saved.id, saved.actor, saved.host, saved.investigation_id, saved.state, saved.revision) != (
        row.id,
        row.actor,
        row.host,
        row.investigation_id,
        row.state,
        row.revision,
    ):
        raise HistoryError("history_unsupported", "Saved turn metadata is inconsistent", ErrorKind.CONFLICT)
    return row, saved


def save_turn(row: TurnRow, saved: SavedTurn, maximum: int = 2097152) -> None:
    """Persist snapshot and indexed lifecycle together without allowing oversized content."""
    encoded = saved.model_dump_json()
    if len(encoded.encode()) > maximum:
        raise capacity()
    row.snapshot, row.snapshot_bytes = encoded, len(encoded.encode())
    row.state, row.revision, row.updated_at = saved.state, saved.revision, utc_text(saved.updated_at)


class SQLiteTurnStore:
    """Serialize receipt admission and revisioned turn lifecycle on the owned database worker."""

    def __init__(self, database: PersistentDatabase, limits: StorageLimits | None = None) -> None:
        """Use short transactions and the archive's explicit capacity policy."""
        self.database = database
        self.limits = limits or StorageLimits()
        self.archive = SQLiteInvestigations(database, self.limits)

    async def submission(self, actor: str, submission_id: str, input_digest: str) -> SavedTurn | None:
        """Read a receipt independently of current models, hosts, workspaces, and running scopes."""
        return await self.database.transaction(lambda session: _submission(session, actor, submission_id, input_digest))

    async def accept(
        self, actor: str, command: StartTurn, input_digest: str, request_id: str, now: datetime
    ) -> AcceptedTurn:
        """Commit receipt, turn, reservations, parent resolution, and preferences in one transaction."""
        command = command.model_copy(deep=True)

        def accepting(session: Session) -> AcceptedTurn:
            """Recheck duplicates atomically before any mutable admission validation."""
            prior = _submission(session, actor, command.root.submission_id, input_digest)
            if prior is not None:
                return AcceptedTurn(snapshot=prior, created=False)
            row = owned(session, actor, command.root.investigation_id)
            if session.get(ActiveTurnScopeRow, (actor, row.host)) is not None:
                raise conflict("turn_busy", "A diagnostic turn is already running on this host")
            parent = (
                owned_turn(session, actor, command.root.clarification_of)[1]
                if isinstance(command.root, ClarificationTurn)
                else None
            )
            workspace = decode_value(InvestigationWorkspace, row.workspace)
            saved = accepted_snapshot(actor, row.host, command, workspace, parent, request_id, now)
            if archive_view(session, row).turn_count >= self.limits.turns_per_investigation:
                raise capacity()
            workspace = accepted_workspace(workspace, saved)
            row.reserved_bytes = self.limits.snapshot_bytes
            self.archive.check_capacity(session, actor, row, workspace)
            return self._accept(session, row, saved, parent, workspace, input_digest, now)

        return await self.database.transaction(accepting, write=True)

    def _accept(
        self,
        session: Session,
        archive: InvestigationRow,
        saved: SavedTurn,
        parent: SavedTurn | None,
        workspace: InvestigationWorkspace,
        digest: str,
        now: datetime,
    ) -> AcceptedTurn:
        """Write already-validated admission values before returning a runnable snapshot."""
        timestamp = utc_text(now)
        row = TurnRow(
            id=saved.id,
            investigation_id=saved.investigation_id,
            actor=saved.actor,
            host=saved.host,
            submission_id=saved.submission_id,
            input_digest=digest,
            request_id=saved.request_id,
            created_at=timestamp,
        )
        save_turn(row, saved, self.limits.snapshot_bytes)
        archive.reserved_bytes -= row.snapshot_bytes
        archive.workspace, archive.active_turn_id = workspace.model_dump_json(), saved.id
        archive.title, archive.updated_at = archive.title or saved.query[:120], timestamp
        session.add(row)
        session.flush()
        session.add(ActiveTurnScopeRow(actor=saved.actor, host=saved.host, turn_id=saved.id))
        session.add(
            SubmissionReceiptRow(
                actor=saved.actor,
                submission_id=saved.submission_id,
                input_digest=digest,
                turn_id=saved.id,
                investigation_id=saved.investigation_id,
                accepted_at=timestamp,
            )
        )
        if parent is not None:
            parent_row, _ = owned_turn(session, saved.actor, parent.id)
            save_turn(
                parent_row,
                parent.model_copy(
                    update={"resolved_by_turn_id": saved.id, "revision": parent.revision + 1, "updated_at": now}
                ),
            )
        prefs = actor_workspace(session, saved.actor)
        save_actor_workspace(
            session,
            saved.actor,
            prefs.model_copy(
                update={
                    "revision": prefs.revision + 1,
                    "last_investigation_id": archive.id,
                    "host": saved.host,
                    "model": saved.model,
                }
            ),
            timestamp,
        )
        session.flush()
        self.archive.check_capacity(session, saved.actor, archive, workspace)
        return AcceptedTurn(snapshot=saved, created=True)

    async def update(self, actor: str, turn_id: str, update: TurnUpdate, now: datetime) -> SavedTurn:
        """Save bounded progress and consume its already-reserved snapshot allowance."""
        update = update.model_copy(deep=True)

        def updating(session: Session) -> SavedTurn:
            """Compare indexed revision and atomically replace the public snapshot."""
            row, current = owned_turn(session, actor, turn_id)
            saved = updated_snapshot(current, update, now)
            save_turn(row, saved, self.limits.snapshot_bytes)
            owned(session, actor, saved.investigation_id).reserved_bytes = (
                self.limits.snapshot_bytes - row.snapshot_bytes
            )
            return saved

        return await self.database.transaction(updating, write=True)

    async def finish(self, actor: str, turn_id: str, outcome: TurnOutcome, now: datetime) -> SavedTurn:
        """Save terminal answer and context and release the active lease before publication."""
        outcome = outcome.model_copy(deep=True)

        def finishing(session: Session) -> SavedTurn:
            """Perform the same terminal CAS for completion, Stop, failure, and interruption."""
            row, current = owned_turn(session, actor, turn_id)
            saved = finished_snapshot(current, outcome, now)
            archive = owned(session, actor, saved.investigation_id)
            context = TypeAdapter(tuple[ModelMessage, ...]).validate_json(archive.context)
            archive.context = context_json(append_context(context, saved))
            archive.reserved_bytes, archive.active_turn_id, archive.updated_at = 0, None, utc_text(now)
            save_turn(row, saved, self.limits.snapshot_bytes)
            session.flush()
            self.archive.check_capacity(
                session, actor, archive, decode_value(InvestigationWorkspace, archive.workspace)
            )
            session.execute(delete(ActiveTurnScopeRow).where(ActiveTurnScopeRow.turn_id == turn_id))
            return saved

        return await self.database.transaction(finishing, write=True)

    async def context(self, actor: str, investigation_id: str) -> tuple[ModelMessage, ...]:
        """Load only the compact plain successful-question context after checking ownership."""
        return await self.database.transaction(
            lambda session: TypeAdapter(tuple[ModelMessage, ...]).validate_json(
                owned(session, actor, investigation_id).context
            )
        )
