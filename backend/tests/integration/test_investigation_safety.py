import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from docksight.application.investigations.contracts import InvestigationView
from docksight.application.investigations.ports import SelectedDiagnostics
from docksight.application.ports.models import ModelReply
from docksight.bootstrap import Settings, build_components
from docksight.main import create_app
from tests.fakes import FakeRuntime, ScriptedModel
from tests.integration.test_investigations_api import HEADERS, TOKEN, history_client
from tests.unit.application.investigations.test_runner import ControlledDiagnostics


@pytest.mark.parametrize("operation", ["draft", "submission"])
def test_expanded_redaction_is_rejected_without_disabling_other_actor_writes(tmp_path: Path, operation: str) -> None:
    with history_client(tmp_path / "state.sqlite3") as api:
        identity = str(uuid4())
        api.post("/api/v1/investigations", headers=HEADERS, json={"id": identity, "host": "local"})
        path = f"/api/v1/investigations/{identity}"
        if operation == "draft":
            response = api.patch(
                path + "/workspace", headers=HEADERS, json={"expected_revision": 0, "draft": "token=x " * 500}
            )
        else:
            response = api.post(
                path + "/turns",
                headers=HEADERS,
                json={
                    "kind": "question",
                    "expected_revision": 0,
                    "submission_id": str(uuid4()),
                    "query": "token=x " * 500,
                },
            )
        assert response.status_code == 422
        assert response.json()["code"] in {"invalid_workspace", "invalid_query"}
        bob = {"Authorization": "Bearer bob-token-at-least-24-characters"}
        unrelated = api.post("/api/v1/investigations", headers=bob, json={"id": str(uuid4()), "host": "local"})
        assert unrelated.status_code == 201
        assert api.get(path, headers=HEADERS).json()["turn_count"] == 0


def test_submitted_container_labels_are_redacted_in_workspace_and_accepted_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    with history_client(path) as api:
        identity = str(uuid4())
        api.post("/api/v1/investigations", headers=HEADERS, json={"id": identity, "host": "local"})
        target = {"kind": "container", "id": "a" * 64, "name": TOKEN}
        workspace = api.patch(
            f"/api/v1/investigations/{identity}/workspace",
            headers=HEADERS,
            json={
                "expected_revision": 0,
                "target": target,
                "selected_container": target,
            },
        )
        assert workspace.status_code == 200
        assert workspace.json()["target"]["name"] == "[REDACTED]"
        assert workspace.json()["selected_container"]["name"] == "[REDACTED]"
        accepted = api.post(
            f"/api/v1/investigations/{identity}/turns",
            headers=HEADERS,
            json={
                "kind": "question",
                "submission_id": str(uuid4()),
                "expected_revision": 1,
                "query": "Inspect",
                "target": target,
            },
        )
        assert accepted.status_code == 202
        saved = accepted.json()["snapshot"]
        assert saved["target"]["name"] == "[REDACTED]"
        api.get(f"/api/v1/turns/{saved['id']}/events", headers=HEADERS)
        with closing(sqlite3.connect(path)) as connection:
            assert TOKEN not in connection.execute("SELECT workspace FROM investigations").fetchone()[0]
            assert TOKEN not in connection.execute("SELECT snapshot FROM turns").fetchone()[0]


@pytest.mark.parametrize("operation", ["draft", "submission"])
def test_sensitive_group_lookup_identity_is_rejected_before_storage(tmp_path: Path, operation: str) -> None:
    with history_client(tmp_path / "state.sqlite3") as api:
        identity = str(uuid4())
        api.post("/api/v1/investigations", headers=HEADERS, json={"id": identity, "host": "local"})
        target = {"kind": "compose", "name": TOKEN}
        path = f"/api/v1/investigations/{identity}"
        if operation == "draft":
            response = api.patch(path + "/workspace", headers=HEADERS, json={"expected_revision": 0, "target": target})
        else:
            response = api.post(
                path + "/turns",
                headers=HEADERS,
                json={
                    "kind": "question",
                    "submission_id": str(uuid4()),
                    "expected_revision": 0,
                    "query": "Inspect",
                    "target": target,
                },
            )
        assert response.status_code == 422 and response.json()["code"] == "invalid_target"
        assert TOKEN not in response.text


@pytest.mark.parametrize("field", ["id", "actor", "host", "investigation_id", "state", "revision"])
def test_public_archive_reads_withhold_valid_but_inconsistent_turn_snapshots(tmp_path: Path, field: str) -> None:
    path = tmp_path / "state.sqlite3"
    model = ScriptedModel(
        [ModelReply("Ready"), ModelReply('{"summary":"Saved answer","uncertain":true,"evidence_ids":[],"widgets":[]}')]
    )
    with history_client(path, model) as api:
        identity = str(uuid4())
        api.post("/api/v1/investigations", headers=HEADERS, json={"id": identity, "host": "local"})
        saved = api.post(
            f"/api/v1/investigations/{identity}/turns",
            headers=HEADERS,
            json={
                "kind": "question",
                "submission_id": str(uuid4()),
                "expected_revision": 0,
                "query": "Inspect",
            },
        ).json()["snapshot"]
        turn_id = saved["id"]
        api.get(f"/api/v1/turns/{turn_id}/events", headers=HEADERS)
        with closing(sqlite3.connect(path)) as connection:
            snapshot = json.loads(connection.execute("SELECT snapshot FROM turns WHERE id=?", (turn_id,)).fetchone()[0])
            values = {
                "id": str(uuid4()),
                "actor": "foreign",
                "host": "other",
                "investigation_id": str(uuid4()),
                "state": "stopped",
                "revision": 99,
            }
            snapshot[field] = values[field]
            snapshot["query"] = "foreign-snapshot-bytes"
            connection.execute("UPDATE turns SET snapshot=? WHERE id=?", (json.dumps(snapshot), turn_id))
            connection.commit()
        read = api.get(f"/api/v1/turns/{turn_id}", headers=HEADERS)
        assert read.status_code == 409 and read.json()["code"] == "history_unsupported"
        for suffix in ("", "/turns"):
            page = api.get(f"/api/v1/investigations/{identity}" + suffix, headers=HEADERS)
            assert page.status_code == 200
            items = page.json()["turns"]["items"] if not suffix else page.json()["items"]
            assert items == [{"id": turn_id, "code": "history_unsupported"}]
            assert "foreign-snapshot-bytes" not in page.text


async def test_two_clients_detail_acceptance_boundary_never_returns_running_turn_without_active_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(api_token=TOKEN, state_path=tmp_path / "state.sqlite3", _env_file=None)
    runtime = FakeRuntime()
    components = build_components(settings, reader=runtime, writer=runtime, model=ScriptedModel([]))
    source = ControlledDiagnostics()

    async def selected(selection: object) -> SelectedDiagnostics:
        """Hold accepted work so another client can observe and Stop the same turn."""
        return SelectedDiagnostics(source, None)

    components.runner.factory = selected
    app = create_app(settings, components)
    async with app.router.lifespan_context(app):
        async with (
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=HEADERS) as first,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test", headers=HEADERS
            ) as second,
        ):
            identity = str(uuid4())
            await first.post("/api/v1/investigations", json={"id": identity, "host": "local"})
            value = {"kind": "question", "submission_id": str(uuid4()), "expected_revision": 0, "query": "Inspect"}
            original = components.investigations.archive.read
            accepted: list[str] = []
            intercept = True

            async def after_metadata(actor: str, investigation_id: str) -> InvestigationView:
                """Commit the other client's turn after a standalone metadata read completes."""
                nonlocal intercept
                result = await original(actor, investigation_id)
                if intercept:
                    intercept = False
                    response = await second.post(f"/api/v1/investigations/{identity}/turns", json=value)
                    assert response.status_code == 202
                    accepted.append(response.json()["snapshot"]["id"])
                return result

            monkeypatch.setattr(components.investigations.archive, "read", after_metadata)
            response = await first.get(f"/api/v1/investigations/{identity}")
            assert response.status_code == 200
            detail = response.json()
            running = [row["id"] for row in detail["turns"]["items"] if row.get("state") == "running"]
            assert running == ([detail["active_turn_id"]] if detail["active_turn_id"] else [])
            if not accepted:
                intercept = False
                saved = await second.post(f"/api/v1/investigations/{identity}/turns", json=value)
                accepted.append(saved.json()["snapshot"]["id"])
            current = (await first.get(f"/api/v1/investigations/{identity}")).json()
            assert current["active_turn_id"] == accepted[0]
            assert current["turns"]["items"][0]["id"] == accepted[0]
            observer = components.runner.observe("operator", accepted[0])
            try:
                assert (await anext(observer)).state == "running"
                stopped = await second.post(f"/api/v1/turns/{accepted[0]}/cancel")
                assert stopped.status_code == 200 and stopped.json()["state"] == "stopped"
                assert [snapshot.state async for snapshot in observer][-1] == "stopped"
            finally:
                await observer.aclose()


def test_diagnosis_action_audit_retains_server_request_and_turn_after_deletion_restart(tmp_path: Path) -> None:
    path, identity = tmp_path / "state.sqlite3", str(uuid4())
    model = ScriptedModel(
        [
            ModelReply("Ready"),
            ModelReply('{"summary":"Current evidence","uncertain":true,"evidence_ids":[],"widgets":[]}'),
        ]
    )
    with history_client(path, model) as api:
        api.post("/api/v1/investigations", headers=HEADERS, json={"id": identity, "host": "local"})
        accepted = api.post(
            f"/api/v1/investigations/{identity}/turns",
            headers=HEADERS | {"X-Request-ID": "caller-fake"},
            json={
                "kind": "question",
                "submission_id": str(uuid4()),
                "expected_revision": 0,
                "query": "Inspect worker",
                "target": {"kind": "container", "id": "a" * 64, "name": "worker"},
            },
        )
        saved = accepted.json()["snapshot"]
        assert saved["request_id"] == accepted.headers["x-request-id"] != "caller-fake"
        api.get(f"/api/v1/turns/{saved['id']}/events", headers=HEADERS)
        final = api.get(f"/api/v1/turns/{saved['id']}", headers=HEADERS).json()
        action = next(card for card in final["answer"]["widgets"] if card["widget_type"] == "container_status")[
            "actions"
        ][0]
        executed = api.post(
            f"/api/v1/actions/{action['id']}/execute",
            headers=HEADERS | {"Idempotency-Key": "audit-key"},
            json={"confirmed": True},
        )
        assert executed.status_code == 200
        assert api.delete(f"/api/v1/investigations/{identity}", headers=HEADERS).status_code == 204
    with history_client(path):
        with closing(sqlite3.connect(path)) as connection:
            rows = connection.execute(
                "SELECT request_id, turn_id FROM action_audit WHERE action_id=?", (action["id"],)
            ).fetchall()
        assert len(rows) == 4
        assert set(rows) == {(saved["request_id"], saved["id"])}
