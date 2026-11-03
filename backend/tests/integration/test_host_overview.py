import json
import os
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from docksight.application.ports.models import ModelReply, ToolCall
from docksight.bootstrap import Settings, build_components
from docksight.domain.errors import DockSightError, ErrorKind
from docksight.domain.runtime import ContainerSnapshot
from docksight.main import create_app
from tests.fakes import DiscoveryRuntime, ScriptedModel
from tests.integration.live_e2e.cases import Case
from tests.integration.live_e2e.checks import check_answer
from tests.integration.live_e2e.lab import ComposeLab
from tests.integration.live_e2e.server import FixtureRuntime


class UnavailableActionRuntime(DiscoveryRuntime):
    """Keep collected inventory and logs while one member becomes unavailable to action preparation."""

    def __init__(self, code: str) -> None:
        """Choose the typed failure returned by the later exact-container read."""
        super().__init__()
        self.code = code

    async def inspect(self, host: str, container_id: str) -> ContainerSnapshot:
        """Fail action preparation for one member after its inventory and logs have already been collected."""
        if container_id == "2" * 64:
            raise DockSightError(self.code, "Action preparation is unavailable", ErrorKind.NOT_FOUND)
        return await super().inspect(host, container_id)


def _proposal() -> ModelReply:
    """Omit model-selected widgets so assertions exercise retained server observations."""
    return ModelReply(
        json.dumps(
            {
                "summary": "Several containers need inspection; the underlying causes remain unknown.",
                "uncertain": True,
                "evidence_ids": [],
                "widgets": [],
            }
        )
    )


def _events(response: Any) -> list[dict[str, Any]]:
    """Decode the public event stream without depending on private diagnostic context."""
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_model_cannot_replace_a_host_overview_with_an_unrequested_project_choice() -> None:
    runtime = DiscoveryRuntime()
    runtime.rows = (*runtime.rows, replace(runtime.item, id="4" * 64, name="standalone", compose_project=None))
    model = ScriptedModel(
        [
            ModelReply(
                "",
                (
                    ToolCall(
                        "hostile-choice",
                        "request_group_selection",
                        {
                            "candidates": [
                                {"kind": "compose", "name": "vintoria-infra"},
                                {"kind": "compose", "name": "other-project"},
                            ]
                        },
                    ),
                ),
            ),
            ModelReply("Ready"),
            _proposal(),
        ]
    )
    settings = Settings(api_token="host-overview-integration-token-24", _env_file=None)
    components = build_components(settings, reader=runtime, writer=runtime, model=model)
    with TestClient(create_app(settings, components)) as api:
        events = _events(
            api.post(
                "/api/v1/chat/turns",
                headers={"Authorization": "Bearer host-overview-integration-token-24"},
                json={"host": "local", "query": "What happened?"},
            )
        )
    assert events[-1]["type"] == "turn.completed", events[-1]
    assert not any(row["type"] == "clarification.required" for row in events)
    answer = next(row["answer"] for row in events if row["type"] == "answer.ready")
    assert answer["group"] is None
    overview = answer["host_overview"]
    assert overview["total"] == overview["attention"] == 4
    references = {row["id"]: row for row in answer["evidence"]}
    primary = references[overview["evidence_id"]]
    assert (primary["kind"], primary["host"], primary["container_id"]) == ("host", "local", None)
    assert {row["container_id"] for row in overview["logs"] if row["state"] == "collected"} == set(runtime.reads)
    assert len(runtime.reads) == 4
    assert len(answer["widgets"]) == 8
    denied = [
        json.loads(message.content)
        for messages, _ in model.requests
        for message in messages
        if message.role == "tool" and message.tool_call_id == "hostile-choice"
    ]
    assert denied and all("error" in result for result in denied)
    assert not runtime.mutations


def test_host_overview_can_narrow_to_one_fresh_exact_container_in_the_same_session() -> None:
    runtime = DiscoveryRuntime()
    proposal = json.loads(_proposal().content)
    proposal["widgets"] = [
        {"widget_type": "container_status", "evidence_ids": ["e1"]},
        {"widget_type": "log_anomalies", "evidence_ids": ["e2"]},
    ]
    model = ScriptedModel([ModelReply("Ready"), _proposal(), ModelReply("Ready"), ModelReply(json.dumps(proposal))])
    settings = Settings(api_token="host-narrow-integration-token-24", _env_file=None)
    components = build_components(settings, reader=runtime, writer=runtime, model=model)
    headers = {"Authorization": "Bearer host-narrow-integration-token-24"}
    with TestClient(create_app(settings, components)) as api:
        first = _events(
            api.post("/api/v1/chat/turns", headers=headers, json={"host": "local", "query": "What happened?"})
        )
        assert first[-1]["type"] == "turn.completed", first[-1]
        assert not any(row["type"] == "clarification.required" for row in first)
        original = next(row["answer"] for row in first if row["type"] == "answer.ready")
        runtime.reads.clear()
        runtime.rows = (*runtime.rows[:2], replace(runtime.rows[2], restart_count=7))
        second = _events(
            api.post(
                "/api/v1/chat/turns",
                headers=headers,
                json={
                    "host": "local",
                    "session_id": first[0]["session_id"],
                    "query": "Inspect this exact container",
                    "container_id": "3" * 64,
                },
            )
        )
    assert second[-1]["type"] == "turn.completed", second[-1]
    answer = next(row["answer"] for row in second if row["type"] == "answer.ready")
    assert second[0]["session_id"] == first[0]["session_id"]
    assert answer["host_overview"] is None and answer["group"] is None
    assert runtime.reads == ["3" * 64]
    assert {row["container_id"] for row in answer["evidence"]} == {"3" * 64}
    status = next(row for row in answer["widgets"] if row["widget_type"] == "container_status")
    assert (status["snapshot"]["id"], status["snapshot"]["restart_count"]) == ("3" * 64, 7)
    assert all(row["restart_count"] == 0 for row in original["host_overview"]["members"])


@pytest.mark.parametrize("code", ["container_not_found", "runtime_timeout", "action_unavailable"])
def test_unavailable_member_actions_do_not_discard_collected_host_observations(code: str) -> None:
    runtime = UnavailableActionRuntime(code)
    model = ScriptedModel([ModelReply("Ready"), _proposal(), _proposal()])
    settings = Settings(api_token="host-actions-integration-token-24", _env_file=None)
    components = build_components(settings, reader=runtime, writer=runtime, model=model)
    with TestClient(create_app(settings, components)) as api:
        events = _events(
            api.post(
                "/api/v1/chat/turns",
                headers={"Authorization": "Bearer host-actions-integration-token-24"},
                json={"host": "local", "query": "What happened?"},
            )
        )
    assert events[-1]["type"] == "turn.completed", events[-1]
    answer = next(row["answer"] for row in events if row["type"] == "answer.ready")
    assert answer["host_overview"]["total"] == 3
    cards = [card for card in answer["widgets"] if card["widget_type"] == "container_status"]
    affected = next(card for card in cards if card["snapshot"]["id"] == "2" * 64)
    assert affected["actions"] == [] and affected["actions_code"] == code
    assert affected["recommendation"] is None
    assert any(card["actions"] for card in cards if card is not affected)
    assert len(model.requests) == 2
    assert len(runtime.reads) == 3 and not runtime.mutations


@pytest.mark.docker
@pytest.mark.skipif(os.getenv("DOCKSIGHT_TEST_DOCKER") != "1", reason="Set DOCKSIGHT_TEST_DOCKER=1")
def test_real_docker_host_overview_crosses_projects_and_retains_ungrouped_failure() -> None:
    """Exercise actual Docker reads, authenticated HTTP and SSE without any local or cloud model calls."""
    case = Case("host-overview-scripted", ("backend",), group=True, spelling="unscoped")
    lab = ComposeLab(case)
    try:
        lab.start()
        runtime = FixtureRuntime(lab)
        model = ScriptedModel([ModelReply("Ready"), _proposal()])
        settings = Settings(api_token="real-host-overview-integration-token-24", _env_file=None)
        components = build_components(settings, reader=runtime, writer=runtime, model=model)
        components.closers.append(runtime.close)
        with TestClient(create_app(settings, components)) as api:
            events = _events(
                api.post(
                    "/api/v1/chat/turns",
                    headers={"Authorization": "Bearer real-host-overview-integration-token-24"},
                    json={"host": "e2e", "query": "What happened?"},
                )
            )
        check_answer(events, lab, case)
        assert len(model.requests) == 2
    finally:
        lab.close()
