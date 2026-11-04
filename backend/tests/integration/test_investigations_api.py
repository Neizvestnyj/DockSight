import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from docksight.application.ports.models import ModelReply
from docksight.bootstrap import Settings, build_components
from docksight.main import create_app
from tests.fakes import DiscoveryRuntime, FakeRuntime, ScriptedModel

TOKEN = "history-token-at-least-24-characters"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def history_client(path: Path, model: ScriptedModel | None = None, runtime: FakeRuntime | None = None) -> TestClient:
    """Build production persistence against an explicitly isolated temporary SQLite file."""
    settings = Settings(
        api_token=TOKEN, api_tokens={"bob": "bob-token-at-least-24-characters"}, state_path=path, _env_file=None
    )
    runtime = runtime or FakeRuntime()
    components = build_components(settings, reader=runtime, writer=runtime, model=model or ScriptedModel([]))
    return TestClient(create_app(settings, components))


def test_acceptance_snapshot_replay_and_restart_do_not_generate_twice(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelReply("Ready"),
            ModelReply('{"summary":"Saved answer","uncertain":true,"evidence_ids":[],"widgets":[]}'),
        ]
    )
    identity = str(uuid4())
    submission = {"kind": "question", "submission_id": str(uuid4()), "expected_revision": 0, "query": "Inspect"}
    path = tmp_path / "state.sqlite3"
    with history_client(path, model) as api:
        created = api.post("/api/v1/investigations", headers=HEADERS, json={"id": identity, "host": "local"})
        assert created.status_code == 201
        accepted = api.post(f"/api/v1/investigations/{identity}/turns", headers=HEADERS, json=submission)
        assert accepted.status_code == 202
        turn = accepted.json()["snapshot"]
        observed = api.get(f"/api/v1/turns/{turn['id']}/events", headers=HEADERS)
        frames = [json.loads(line[6:]) for line in observed.text.splitlines() if line.startswith("data: ")]
        assert frames[-1]["state"] == "completed"
        assert frames[-1]["request_id"] == accepted.headers["x-request-id"]
        assert observed.headers["x-request-id"] != turn["request_id"]
        replay = api.post(f"/api/v1/investigations/{identity}/turns", headers=HEADERS, json=submission)
        assert replay.status_code == 202 and replay.json()["created"] is False
        assert replay.json()["snapshot"]["id"] == turn["id"]
        assert len(model.requests) == 2
    restarted_model = ScriptedModel([])
    with history_client(path, restarted_model) as api:
        saved = api.get(f"/api/v1/turns/{turn['id']}", headers=HEADERS)
        assert saved.json()["answer"]["summary"] == "Saved answer"
        detail = api.get(f"/api/v1/investigations/{identity}", headers=HEADERS).json()
        assert detail["turns"]["items"][0]["id"] == turn["id"]
        assert detail["active_turn_id"] is None
        assert api.get(f"/api/v1/turns/{turn['id']}/events", headers=HEADERS).status_code == 200
    assert restarted_model.requests == []


def test_owned_latest_ten_and_older_pages_do_not_remove_archives(tmp_path: Path) -> None:
    identities = [str(uuid4()) for _ in range(13)]
    bob = {"Authorization": "Bearer bob-token-at-least-24-characters"}
    with history_client(tmp_path / "state.sqlite3") as api:
        for identity in identities:
            body = {"id": identity, "host": "local"}
            assert api.post("/api/v1/investigations", headers=HEADERS, json=body).json()["id"] == identity
            assert api.post("/api/v1/investigations", headers=HEADERS, json=body).status_code == 201
        page = api.get("/api/v1/investigations", headers=HEADERS).json()
        assert [row["id"] for row in page["items"]] == list(reversed(identities[-10:]))
        older = api.get("/api/v1/investigations", headers=HEADERS, params={"before": page["next_cursor"]}).json()
        assert [row["id"] for row in older["items"]] == list(reversed(identities[:3]))
        assert older["next_cursor"] is None
        assert api.get("/api/v1/investigations", headers=bob).json()["items"] == []
        for path in (f"/investigations/{identities[0]}", f"/investigations/{uuid4()}"):
            denied = api.get("/api/v1" + path, headers=bob)
            assert denied.status_code == 404 and denied.json()["code"] == "history_not_found"
        cross_actor = api.get("/api/v1/investigations", headers=bob, params={"before": page["next_cursor"]})
        assert cross_actor.status_code == 400
        assert api.get(f"/api/v1/investigations/{identities[0]}", headers=HEADERS).status_code == 200


def test_workspace_conflicts_return_current_safe_snapshot_and_validate_preferences(tmp_path: Path) -> None:
    with history_client(tmp_path / "state.sqlite3") as api:
        identity = str(uuid4())
        api.post("/api/v1/investigations", headers=HEADERS, json={"id": identity, "host": "local"})
        path = f"/api/v1/investigations/{identity}/workspace"
        first = api.patch(path, headers=HEADERS, json={"expected_revision": 0, "draft": f"Inspect {TOKEN}"})
        assert first.json()["draft"] == "Inspect [REDACTED]"
        conflict = api.patch(path, headers=HEADERS, json={"expected_revision": 0, "draft": "Other tab"})
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "workspace_conflict"
        assert conflict.json()["current"] == first.json()
        assert TOKEN not in conflict.text
        preference = {
            "expected_revision": 0,
            "last_investigation_id": identity,
            "host": "local",
            "model": {"provider": "ollama", "model": "qwen3.5:9b"},
        }
        current = api.patch("/api/v1/me/workspace", headers=HEADERS, json=preference)
        assert current.status_code == 200 and current.json()["revision"] == 1
        stale = api.patch("/api/v1/me/workspace", headers=HEADERS, json={"expected_revision": 0, "host": "local"})
        assert stale.status_code == 409 and stale.json()["current"] == current.json()
        bad_model = api.patch(
            "/api/v1/me/workspace",
            headers=HEADERS,
            json={
                "expected_revision": 1,
                "model": {"provider": "ollama", "model": "unlisted"},
            },
        )
        assert bad_model.status_code == 422 and bad_model.json()["code"] == "model_not_listed"
        assert api.get("/api/v1/me/workspace", headers=HEADERS).json() == current.json()


@pytest.mark.parametrize(
    "case",
    [
        "unknown_field",
        "bad_uuid",
        "large_query",
        "bad_revision",
        "boolean_revision",
        "oversized_revision",
        "clarification_query",
        "authoritative_id",
    ],
)
def test_submission_transport_rejects_invalid_or_authoritative_fields(tmp_path: Path, case: str) -> None:
    identity = str(uuid4())
    value = {"kind": "question", "submission_id": str(uuid4()), "query": "Inspect", "expected_revision": 0}
    changes = {
        "unknown_field": {"token": "private-sentinel"},
        "bad_uuid": {"submission_id": "wrong"},
        "large_query": {"query": "q" * 4001},
        "bad_revision": {"expected_revision": -1},
        "boolean_revision": {"expected_revision": True},
        "oversized_revision": {"expected_revision": 2**53},
        "clarification_query": {
            "kind": "clarification",
            "clarification_of": str(uuid4()),
            "expected_parent_revision": 0,
            "target": {"kind": "compose", "name": "web"},
        },
        "authoritative_id": {"investigation_id": str(uuid4()), "actor": "bob", "turn_id": str(uuid4())},
    }
    with history_client(tmp_path / "state.sqlite3") as api:
        api.post("/api/v1/investigations", headers=HEADERS, json={"id": identity, "host": "local"})
        response = api.post(f"/api/v1/investigations/{identity}/turns", headers=HEADERS, json=value | changes[case])
        assert response.status_code == 422
        assert response.headers["cache-control"] == "no-store"
        assert "private-sentinel" not in response.text
        assert api.get(f"/api/v1/investigations/{identity}/turns", headers=HEADERS).json()["items"] == []


@pytest.mark.parametrize("query", ["limit=0", "limit=51", "before=broken", "before=", "before=" + "x" * 1025])
def test_history_pages_reject_unbounded_or_invalid_cursors(tmp_path: Path, query: str) -> None:
    with history_client(tmp_path / "state.sqlite3") as api:
        response = api.get("/api/v1/investigations?" + query, headers=HEADERS)
        assert response.status_code in {400, 422}


def test_removed_host_history_and_submission_receipts_remain_readable(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    model = ScriptedModel(
        [
            ModelReply("Ready"),
            ModelReply(
                '{"summary":"Original host","uncertain":true,"evidence_ids":[],"widgets":[]}',
            ),
        ]
    )
    identity = str(uuid4())
    value = {"kind": "question", "submission_id": str(uuid4()), "expected_revision": 0, "query": "Inspect"}
    with history_client(tmp_path / "state.sqlite3", model, runtime) as api:
        api.post("/api/v1/investigations", headers=HEADERS, json={"id": identity, "host": "local"})
        accepted = api.post(f"/api/v1/investigations/{identity}/turns", headers=HEADERS, json=value).json()
        turn_id = accepted["snapshot"]["id"]
        api.get(f"/api/v1/turns/{turn_id}/events", headers=HEADERS)
        with patch.object(runtime, "hosts", return_value=()):
            assert api.get(f"/api/v1/investigations/{identity}", headers=HEADERS).json()["host"] == "local"
            replay = api.post(f"/api/v1/investigations/{identity}/turns", headers=HEADERS, json=value)
            assert replay.status_code == 202 and not replay.json()["created"]
            continuation = api.post(
                f"/api/v1/investigations/{identity}/turns",
                headers=HEADERS,
                json=value | {"submission_id": str(uuid4()), "expected_revision": 1},
            )
            assert continuation.status_code == 404 and continuation.json()["code"] == "host_not_found"
        assert len(model.requests) == 2


def test_legacy_receipt_replay_preserves_exact_submitted_host_scope(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelReply("Ready"),
            ModelReply(
                '{"summary":"Original host","uncertain":true,"evidence_ids":[],"widgets":[]}',
            ),
        ]
    )
    value = {"host": "local", "query": "Inspect", "submission_id": str(uuid4())}
    with history_client(tmp_path / "state.sqlite3", model) as api:
        first = api.post("/api/v1/chat/turns", headers=HEADERS, json=value)
        events = [json.loads(line[6:]) for line in first.text.splitlines() if line.startswith("data: ")]
        changed = api.post(
            "/api/v1/chat/turns",
            headers=HEADERS,
            json=value | {"host": "different", "session_id": events[0]["session_id"]},
        )
        failure = [json.loads(line[6:]) for line in changed.text.splitlines() if line.startswith("data: ")][-1]
        assert failure["type"] == "turn.failed" and failure["code"] == "session_not_found"
        assert len(model.requests) == 2


def test_older_turn_pages_remain_in_display_order_and_foreign_turns_are_not_found(tmp_path: Path) -> None:
    replies = [
        reply
        for _ in range(23)
        for reply in (
            ModelReply("Ready"),
            ModelReply('{"summary":"Saved answer","uncertain":true,"evidence_ids":[],"widgets":[]}'),
        )
    ]
    model = ScriptedModel(replies)
    identity, ids = str(uuid4()), []
    with history_client(tmp_path / "state.sqlite3", model) as api:
        api.post("/api/v1/investigations", headers=HEADERS, json={"id": identity, "host": "local"})
        for revision in range(23):
            accepted = api.post(
                f"/api/v1/investigations/{identity}/turns",
                headers=HEADERS,
                json={
                    "kind": "question",
                    "submission_id": str(uuid4()),
                    "expected_revision": revision,
                    "query": f"Inspect {revision}",
                },
            )
            assert accepted.status_code == 202
            turn_id = accepted.json()["snapshot"]["id"]
            ids.append(turn_id)
            assert api.get(f"/api/v1/turns/{turn_id}/events", headers=HEADERS).status_code == 200
        page = api.get(f"/api/v1/investigations/{identity}/turns", headers=HEADERS).json()
        assert [row["id"] for row in page["items"]] == ids[3:]
        older = api.get(
            f"/api/v1/investigations/{identity}/turns", headers=HEADERS, params={"before": page["next_cursor"]}
        ).json()
        assert [row["id"] for row in older["items"]] == ids[:3]
        assert older["next_cursor"] is None
        wrong_query = api.get("/api/v1/investigations", headers=HEADERS, params={"before": page["next_cursor"]})
        assert wrong_query.status_code == 400
        bob = {"Authorization": "Bearer bob-token-at-least-24-characters"}
        for suffix in ("", "/events", "/cancel"):
            method = api.post if suffix == "/cancel" else api.get
            foreign = method(f"/api/v1/turns/{ids[0]}{suffix}", headers=bob)
            assert foreign.status_code == 404 and foreign.json()["code"] == "history_not_found"
        assert len(model.requests) == 46


def test_clarification_transport_uses_saved_question_parent_revision_and_candidate(tmp_path: Path) -> None:
    runtime = DiscoveryRuntime()
    runtime.rows = (*runtime.rows[:2], replace(runtime.rows[2], name="other-project"))
    model = ScriptedModel(
        [
            ModelReply("Ready"),
            ModelReply(
                '{"summary":"Observed project","uncertain":true,"evidence_ids":[],"widgets":[]}',
            ),
        ]
    )
    identity, query = str(uuid4()), "Could other-project simply be stopped?"
    with history_client(tmp_path / "state.sqlite3", model, runtime) as api:
        api.post("/api/v1/investigations", headers=HEADERS, json={"id": identity, "host": "local"})
        first = api.post(
            f"/api/v1/investigations/{identity}/turns",
            headers=HEADERS,
            json={
                "kind": "question",
                "submission_id": str(uuid4()),
                "expected_revision": 0,
                "query": query,
            },
        ).json()["snapshot"]
        api.get(f"/api/v1/turns/{first['id']}/events", headers=HEADERS)
        parent = api.get(f"/api/v1/turns/{first['id']}", headers=HEADERS).json()
        assert parent["state"] == "awaiting_selection" and model.requests == []
        draft = api.patch(
            f"/api/v1/investigations/{identity}/workspace",
            headers=HEADERS,
            json={"expected_revision": 1, "draft": "A different acknowledged question"},
        ).json()
        value = {
            "kind": "clarification",
            "submission_id": str(uuid4()),
            "expected_revision": draft["revision"],
            "clarification_of": first["id"],
            "expected_parent_revision": parent["revision"],
            "target": {"kind": "compose", "name": "other-project"},
        }
        child = api.post(f"/api/v1/investigations/{identity}/turns", headers=HEADERS, json=value)
        assert child.status_code == 202
        saved = child.json()["snapshot"]
        assert saved["query"] == query and saved["clarification_of"] == first["id"]
        api.get(f"/api/v1/turns/{saved['id']}/events", headers=HEADERS)
        final = api.get(f"/api/v1/turns/{saved['id']}", headers=HEADERS).json()
        assert final["answer"]["group"]["summary"]["name"] == "other-project"
        assert api.get(f"/api/v1/turns/{first['id']}", headers=HEADERS).json()["resolved_by_turn_id"] == saved["id"]
        assert (
            api.get(f"/api/v1/investigations/{identity}", headers=HEADERS).json()["workspace"]["draft"]
            == draft["draft"]
        )
        replay = api.post(f"/api/v1/investigations/{identity}/turns", headers=HEADERS, json=value)
        assert replay.status_code == 202 and not replay.json()["created"]
        conflict = api.post(
            f"/api/v1/investigations/{identity}/turns",
            headers=HEADERS,
            json=value | {"submission_id": str(uuid4()), "expected_revision": 3},
        )
        assert conflict.status_code == 409 and conflict.json()["code"] == "clarification_conflict"
        assert len(model.requests) == 2


def test_delete_history_preserves_actions_idempotency_audit_and_target_guard(tmp_path: Path) -> None:
    class AmbiguousRuntime(FakeRuntime):
        """Fail an actual mutation after dispatch so the saved guard must survive history deletion."""

        async def restart(self, host: str, container_id: str) -> None:
            """Return an ambiguous timeout without executing any real Docker operation."""
            raise TimeoutError()

    path, identity = tmp_path / "state.sqlite3", str(uuid4())
    with history_client(path, runtime=AmbiguousRuntime()) as api:
        api.post("/api/v1/investigations", headers=HEADERS, json={"id": identity, "host": "local"})
        action = api.post(
            "/api/v1/actions", headers=HEADERS, json={"host": "local", "container_id": "a" * 64, "operation": "restart"}
        ).json()
        execute_headers = HEADERS | {"Idempotency-Key": "retained-key"}
        executed = api.post(
            f"/api/v1/actions/{action['id']}/execute", headers=execute_headers, json={"confirmed": True}
        )
        assert executed.json()["state"] == "indeterminate"
        with closing(sqlite3.connect(path)) as connection:
            before = {
                table: connection.execute(f"SELECT * FROM {table}").fetchall()
                for table in ("prepared_actions", "action_audit", "target_guards")
            }
        assert api.get(f"/api/v1/investigations/{identity}", headers=HEADERS).status_code == 200
        assert api.delete(f"/api/v1/investigations/{identity}", headers=HEADERS).status_code == 204
        assert api.get(f"/api/v1/investigations/{identity}", headers=HEADERS).status_code == 404
        replay = api.post(f"/api/v1/actions/{action['id']}/execute", headers=execute_headers, json={"confirmed": True})
        assert replay.json() == executed.json()
        with closing(sqlite3.connect(path)) as connection:
            after = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in before}
        assert after == before


def test_deleting_saved_turns_keeps_submission_tombstones_and_selects_next_owned_history(tmp_path: Path) -> None:
    model = ScriptedModel(
        [
            ModelReply("Ready"),
            ModelReply(
                '{"summary":"Saved answer","uncertain":true,"evidence_ids":[],"widgets":[]}',
            ),
        ]
    )
    first, second = str(uuid4()), str(uuid4())
    value = {"kind": "question", "submission_id": str(uuid4()), "expected_revision": 0, "query": "Inspect"}
    with history_client(tmp_path / "state.sqlite3", model) as api:
        for identity in (first, second):
            api.post("/api/v1/investigations", headers=HEADERS, json={"id": identity, "host": "local"})
        accepted = api.post(f"/api/v1/investigations/{second}/turns", headers=HEADERS, json=value).json()
        turn_id = accepted["snapshot"]["id"]
        api.get(f"/api/v1/turns/{turn_id}/events", headers=HEADERS)
        assert api.get("/api/v1/me/workspace", headers=HEADERS).json()["last_investigation_id"] == second
        assert api.delete(f"/api/v1/investigations/{second}", headers=HEADERS).status_code == 204
        assert api.get("/api/v1/me/workspace", headers=HEADERS).json()["last_investigation_id"] == first
        assert api.get(f"/api/v1/turns/{turn_id}", headers=HEADERS).status_code == 404
        replay = api.post(f"/api/v1/investigations/{second}/turns", headers=HEADERS, json=value)
        assert replay.status_code == 404 and replay.json()["code"] == "history_deleted"
        assert len(model.requests) == 2


def test_removed_model_catalog_keeps_history_and_matching_receipts_available(tmp_path: Path) -> None:
    settings = Settings(api_token=TOKEN, state_path=tmp_path / "state.sqlite3", _env_file=None)
    runtime = FakeRuntime()
    model = ScriptedModel(
        [
            ModelReply("Ready"),
            ModelReply(
                '{"summary":"Original model","uncertain":true,"evidence_ids":[],"widgets":[]}',
            ),
        ]
    )
    components = build_components(settings, reader=runtime, writer=runtime, model=model)
    identity = str(uuid4())
    value = {"kind": "question", "submission_id": str(uuid4()), "expected_revision": 0, "query": "Inspect"}
    with TestClient(create_app(settings, components)) as api:
        api.post("/api/v1/investigations", headers=HEADERS, json={"id": identity, "host": "local"})
        original = api.post(f"/api/v1/investigations/{identity}/turns", headers=HEADERS, json=value).json()["snapshot"]
        api.get(f"/api/v1/turns/{original['id']}/events", headers=HEADERS)
        assert components.models is not None
        components.models.catalogs.clear()
        saved = api.get(f"/api/v1/turns/{original['id']}", headers=HEADERS).json()
        assert saved["answer"]["summary"] == "Original model"
        assert api.get(f"/api/v1/investigations/{identity}", headers=HEADERS).status_code == 200
        assert api.get(f"/api/v1/turns/{original['id']}/events", headers=HEADERS).status_code == 200
        replay = api.post(f"/api/v1/investigations/{identity}/turns", headers=HEADERS, json=value)
        assert replay.status_code == 202 and replay.json()["snapshot"] == saved
        rejected = api.post(
            f"/api/v1/investigations/{identity}/turns",
            headers=HEADERS,
            json=value | {"submission_id": str(uuid4()), "expected_revision": 1},
        )
        assert rejected.status_code == 422 and rejected.json()["code"] == "provider_not_configured"
        assert len(model.requests) == 2
