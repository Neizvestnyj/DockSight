from datetime import UTC, datetime, timedelta

import pytest

from docksight.domain.actions import ActionState, PreparedAction
from docksight.domain.errors import DockSightError

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def action() -> PreparedAction:
    return PreparedAction(
        "a1", "operator", "local", "a" * 64, "restart", "v1", NOW + timedelta(minutes=5)
    )


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
def test_invalid_claim_has_no_execution_side_effect(
    actor: str, confirmed: bool, time: datetime
) -> None:
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
