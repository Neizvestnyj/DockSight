from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final = "0001_state"
down_revision: Final = None
branch_labels: Final = None
depends_on: Final = None


def upgrade() -> None:
    """Create the original storage schema without depending on mutable ORM mappings."""
    op.create_table(
        "investigations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("host", sa.String(128), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("workspace", sa.Text, nullable=False),
        sa.Column("context", sa.Text, nullable=False),
        sa.Column("active_turn_id", sa.String(36)),
        sa.Column("reserved_bytes", sa.Integer, nullable=False),
    )
    op.create_index("investigations_activity", "investigations", ["actor", "updated_at", "id"])
    _turns()
    _sessions()
    _actions()


def _turns() -> None:
    """Create content rows, actor-scoped receipts, and active diagnostic reservations."""
    op.create_table(
        "turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "investigation_id", sa.String(36), sa.ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("host", sa.String(128), nullable=False),
        sa.Column("submission_id", sa.String(36), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("snapshot", sa.Text, nullable=False),
        sa.Column("snapshot_bytes", sa.Integer, nullable=False),
        sa.UniqueConstraint("actor", "submission_id"),
        sa.CheckConstraint("snapshot_bytes >= 0 AND snapshot_bytes <= 2097152"),
    )
    op.create_index("turns_chronology", "turns", ["investigation_id", "created_at", "id"])
    op.create_table(
        "submission_receipts",
        sa.Column("actor", sa.String(128), primary_key=True),
        sa.Column("submission_id", sa.String(36), primary_key=True),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("turn_id", sa.String(36), nullable=False),
        sa.Column("investigation_id", sa.String(36), nullable=False),
        sa.Column("accepted_at", sa.String(32), nullable=False),
        sa.Column("archive_deleted_at", sa.String(32)),
    )
    op.create_index("ix_submission_receipts_investigation_id", "submission_receipts", ["investigation_id"])
    op.create_table(
        "active_turn_scopes",
        sa.Column("actor", sa.String(128), primary_key=True),
        sa.Column("host", sa.String(128), primary_key=True),
        sa.Column("turn_id", sa.String(36), sa.ForeignKey("turns.id", ondelete="CASCADE"), nullable=False, unique=True),
    )


def _sessions() -> None:
    """Create independent actor preferences and hashed browser-session records."""
    op.create_table(
        "actor_workspaces",
        sa.Column("actor", sa.String(128), primary_key=True),
        sa.Column("workspace", sa.Text, nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "browser_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("credential_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("last_seen_at", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.String(32), nullable=False),
        sa.Column("revoked_at", sa.String(32)),
    )
    op.create_index("ix_browser_sessions_actor", "browser_sessions", ["actor"])


def _actions() -> None:
    """Create execution and audit records without archive cascade relationships."""
    op.create_table(
        "prepared_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("host", sa.String(128), nullable=False),
        sa.Column("container_id", sa.String(64), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("claimed_at", sa.String(32)),
        sa.Column("dispatched_at", sa.String(32)),
        sa.Column("snapshot", sa.Text, nullable=False),
    )
    op.create_table(
        "target_guards",
        sa.Column("host", sa.String(128), primary_key=True),
        sa.Column("container_id", sa.String(64), primary_key=True),
        sa.Column("active_action_id", sa.String(36), sa.ForeignKey("prepared_actions.id")),
        sa.Column("blocked_action_id", sa.String(36), sa.ForeignKey("prepared_actions.id")),
        sa.Column("revision", sa.Integer, nullable=False),
    )
    op.create_table(
        "action_audit",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("action_id", sa.String(36)),
        sa.Column("request_id", sa.String(128)),
        sa.Column("turn_id", sa.String(36)),
        sa.Column("fields", sa.Text, nullable=False),
    )
