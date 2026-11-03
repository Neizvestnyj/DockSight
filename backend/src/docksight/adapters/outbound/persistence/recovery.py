from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from docksight.adapters.outbound.persistence.actions import hydrate, save_action, save_guard, target_guard
from docksight.adapters.outbound.persistence.database import RecoveryReport
from docksight.adapters.outbound.persistence.rows import PreparedActionRow
from docksight.domain.actions import ActionState
from docksight.domain.errors import DockSightError, ErrorKind


def recover_actions(session: Session) -> RecoveryReport:
    """Settle abandoned claims conservatively and retain dispatch uncertainty before server readiness."""
    failed = indeterminate = 0
    now = datetime.now(UTC)
    rows = session.scalars(
        select(PreparedActionRow).where(PreparedActionRow.phase.in_(("claimed", "dispatching")))
    ).all()
    for row in rows:
        stored = hydrate(row)
        guard = target_guard(session, stored.action)
        if guard.active_action_id != row.id or guard.blocked_action_id is not None:
            raise DockSightError("recovery_required", "Action target guard is inconsistent", ErrorKind.UNAVAILABLE)
        unknown = stored.phase == "dispatching"
        state = ActionState.INDETERMINATE if unknown else ActionState.FAILED
        message = (
            "Action interrupted after dispatch; Docker outcome is unknown"
            if unknown
            else "Action interrupted before dispatch"
        )
        stored.action.finish(state, message)
        save_action(session, replace(stored, phase="terminal"), now, f"action.{state}")
        save_guard(session, guard, None, row.id if unknown else None)
        failed += not unknown
        indeterminate += unknown
    return RecoveryReport(failed_actions=failed, indeterminate_actions=indeterminate)
