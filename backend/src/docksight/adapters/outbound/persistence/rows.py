from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Collect adapter-owned relational mappings without exposing ORM values to ports."""


class InvestigationRow(Base):
    """Persist owned metadata, acknowledged workspace, and bounded model context."""

    __tablename__ = "investigations"
    __table_args__ = (Index("investigations_activity", "actor", "updated_at", "id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor: Mapped[str] = mapped_column(String(128))
    host: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))
    workspace: Mapped[str] = mapped_column(Text, default='{"revision":0}')
    context: Mapped[str] = mapped_column(Text, default="[]")
    active_turn_id: Mapped[str | None] = mapped_column(String(36), default=None)
    reserved_bytes: Mapped[int] = mapped_column(Integer, default=0)


class TurnRow(Base):
    """Index ownership and lifecycle while retaining a bounded versioned public snapshot."""

    __tablename__ = "turns"
    __table_args__ = (
        UniqueConstraint("actor", "submission_id"),
        Index("turns_chronology", "investigation_id", "created_at", "id"),
        CheckConstraint("snapshot_bytes >= 0 AND snapshot_bytes <= 2097152"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"))
    actor: Mapped[str] = mapped_column(String(128))
    host: Mapped[str] = mapped_column(String(128))
    submission_id: Mapped[str] = mapped_column(String(36))
    input_digest: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))
    snapshot: Mapped[str] = mapped_column(Text)
    snapshot_bytes: Mapped[int] = mapped_column(Integer)


class SubmissionReceiptRow(Base):
    """Keep content-free duplicate protection after explicit archive deletion."""

    __tablename__ = "submission_receipts"
    actor: Mapped[str] = mapped_column(String(128), primary_key=True)
    submission_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    input_digest: Mapped[str] = mapped_column(String(64))
    turn_id: Mapped[str] = mapped_column(String(36))
    investigation_id: Mapped[str] = mapped_column(String(36), index=True)
    accepted_at: Mapped[str] = mapped_column(String(32))
    archive_deleted_at: Mapped[str | None] = mapped_column(String(32), default=None)


class ActiveTurnScopeRow(Base):
    """Reserve one running diagnostic per actor and configured host."""

    __tablename__ = "active_turn_scopes"
    actor: Mapped[str] = mapped_column(String(128), primary_key=True)
    host: Mapped[str] = mapped_column(String(128), primary_key=True)
    turn_id: Mapped[str] = mapped_column(ForeignKey("turns.id", ondelete="CASCADE"), unique=True)


class ActorWorkspaceRow(Base):
    """Persist independent actor preferences as a validated versioned value."""

    __tablename__ = "actor_workspaces"
    actor: Mapped[str] = mapped_column(String(128), primary_key=True)
    workspace: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(String(32))


class BrowserSessionRow(Base):
    """Retain hashed browser-session lifecycle fields without cookie secrets."""

    __tablename__ = "browser_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor: Mapped[str] = mapped_column(String(128), index=True)
    credential_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(32))
    last_seen_at: Mapped[str] = mapped_column(String(32))
    expires_at: Mapped[str] = mapped_column(String(32))
    revoked_at: Mapped[str | None] = mapped_column(String(32), default=None)


class PreparedActionRow(Base):
    """Retain detached domain action fields and durable dispatch protection."""

    __tablename__ = "prepared_actions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor: Mapped[str] = mapped_column(String(128))
    host: Mapped[str] = mapped_column(String(128))
    container_id: Mapped[str] = mapped_column(String(64))
    phase: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), default=None)
    claimed_at: Mapped[str | None] = mapped_column(String(32), default=None)
    dispatched_at: Mapped[str | None] = mapped_column(String(32), default=None)
    snapshot: Mapped[str] = mapped_column(Text)


class TargetGuardRow(Base):
    """Keep target blocks independent of archive deletion and action expiry."""

    __tablename__ = "target_guards"
    host: Mapped[str] = mapped_column(String(128), primary_key=True)
    container_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    active_action_id: Mapped[str | None] = mapped_column(ForeignKey("prepared_actions.id"), default=None)
    blocked_action_id: Mapped[str | None] = mapped_column(ForeignKey("prepared_actions.id"), default=None)
    revision: Mapped[int] = mapped_column(Integer, default=0)


class ActionAuditRow(Base):
    """Keep sanitized audit correlated with original requests after archive deletion."""

    __tablename__ = "action_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(128))
    action_id: Mapped[str | None] = mapped_column(String(36), default=None)
    request_id: Mapped[str | None] = mapped_column(String(128), default=None)
    turn_id: Mapped[str | None] = mapped_column(String(36), default=None)
    fields: Mapped[str] = mapped_column(Text)
