from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from docksight.application.investigations.contracts import SavedTurn, StartTurn, WorkspacePatch


def test_workspace_requires_revision_and_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        WorkspacePatch.model_validate({"draft": "question"})
    with pytest.raises(ValidationError):
        WorkspacePatch.model_validate({"expected_revision": 0, "native": {}})


def test_clarification_cannot_replace_the_original_query() -> None:
    with pytest.raises(ValidationError):
        StartTurn.model_validate(
            {
                "kind": "clarification",
                "investigation_id": str(uuid4()),
                "submission_id": str(uuid4()),
                "expected_revision": 0,
                "clarification_of": str(uuid4()),
                "expected_parent_revision": 1,
                "target": {"kind": "compose", "name": "api"},
                "query": "replacement",
            }
        )


def test_snapshot_rejects_naive_dates_and_preview_retention() -> None:
    data = {
        "id": str(uuid4()),
        "investigation_id": str(uuid4()),
        "actor": "alice",
        "host": "local",
        "submission_id": str(uuid4()),
        "request_id": "request-1",
        "query": "Why?",
        "state": "running",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    assert SavedTurn.model_validate(data).schema_version == 1
    with pytest.raises(ValidationError):
        SavedTurn.model_validate({**data, "created_at": datetime(2026, 1, 1)})
    with pytest.raises(ValidationError):
        SavedTurn.model_validate({**data, "schema_version": 99})
