from datetime import UTC, datetime, timedelta

import pytest

from docksight.domain.actions import ActionState, PreparedAction
from docksight.domain.errors import DockSightError

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def action() -> PreparedAction:
    """Build an unclaimed prepared action with a deterministic owner and expiry."""
    return PreparedAction("a1", "operator", "local", "a" * 64, "restart", "v1", NOW + timedelta(minutes=5))


def test_action_can_only_be_claimed_once() -> None:
    item = action()
    assert item.claim("operator", "request-1", True, NOW) is True
    assert item.state == ActionState.RUNNING
    assert item.claim("operator", "request-1", True, NOW) is False
    with pytest.raises(DockSightError, match="another idempotency key"):
        item.claim("operator", "request-2", True, NOW)


@pytest.mark.parametrize(
    ("actor", "confirmed", "time"),
    [
        ("other", True, NOW),
        ("operator", False, NOW),
        ("operator", True, NOW + timedelta(minutes=5)),
    ],
)
def test_invalid_claim_has_no_execution_side_effect(actor: str, confirmed: bool, time: datetime) -> None:
    item = action()
    with pytest.raises(DockSightError):
        item.claim(actor, "request-1", confirmed, time)
    assert item.state != ActionState.RUNNING


def test_completed_action_cannot_be_finished_again() -> None:
    item = action()
    item.claim("operator", "request-1", True, NOW)
    item.finish(ActionState.SUCCEEDED, "Container restarted")
    with pytest.raises(DockSightError):
        item.finish(ActionState.FAILED, "Late failure")
    assert item.state == ActionState.SUCCEEDED


def test_expiry_changes_only_unclaimed_preparations() -> None:
    item = action()
    assert item.expire(NOW) is False
    assert item.expire(NOW + timedelta(minutes=5)) is True
    assert item.state == ActionState.EXPIRED
    assert item.expire(NOW + timedelta(minutes=6)) is False
    running = action()
    running.claim("operator", "request-1", True, NOW)
    assert running.expire(NOW + timedelta(days=1)) is False
    assert running.state == ActionState.RUNNING


def test_reconciliation_invalidation_cannot_rewrite_a_claimed_outcome() -> None:
    item = action()
    item.invalidate()
    assert item.state == ActionState.EXPIRED
    with pytest.raises(DockSightError):
        item.claim("operator", "request-1", True, NOW)
    running = action()
    running.claim("operator", "request-1", True, NOW)
    running.finish(ActionState.INDETERMINATE, "Unknown")
    with pytest.raises(DockSightError):
        running.invalidate()
    assert running.state == ActionState.INDETERMINATE
