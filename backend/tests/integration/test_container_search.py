from typing import Final
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from docksight.adapters.outbound.docker.hosts import HostConfig
from docksight.adapters.outbound.docker.runtime import DockerRuntime
from docksight.application.redaction import Redactor
from docksight.bootstrap import Settings, build_components
from docksight.main import create_app
from tests.fakes import ScriptedModel
from tests.integration.test_api import HEADERS, TOKEN

PATH: Final = "/api/v1/hosts/local/container-search"


def _client() -> TestClient:
    """Build the real runtime adapter and HTTP route against a controlled SDK connection."""
    settings = Settings(state_backend="memory", api_token=TOKEN, _env_file=None)
    runtime = DockerRuntime((HostConfig(id="local"), HostConfig(id="remote")), Redactor((TOKEN,)))
    components = build_components(settings, reader=runtime, writer=runtime, model=ScriptedModel([]))
    return TestClient(create_app(settings, components))


def _row(identity: str, name: str, image: str, labels: dict[str, str] | None = None) -> dict[str, object]:
    """Describe a stopped container in the Docker list response."""
    return {"Id": identity, "Names": [f"/{name}"], "Image": image, "State": "exited", "Labels": labels or {}}


def test_search_finds_stopped_containers_beyond_the_inspected_inventory() -> None:
    sdk = MagicMock()
    sdk.api.containers.return_value = [
        *(_row(f"{index:064x}", "unrelated", "ubuntu:1") for index in range(200)),
        _row("a" * 64, "Commerce_DB", f"db:{TOKEN}", {"com.docker.compose.project": "commerce"}),
    ]
    with patch("docksight.adapters.outbound.docker.runtime.connect", return_value=sdk), _client() as api:
        result = api.get(PATH, params={"q": "  COMMERCE_db  "}, headers=HEADERS)

    assert result.status_code == 200
    assert result.json() == {
        "items": [
            {
                "id": "a" * 64,
                "name": "Commerce_DB",
                "image": "db:[REDACTED]",
                "state": "exited",
                "compose_project": "commerce",
                "swarm_stack": None,
            }
        ],
        "next_cursor": None,
    }
    sdk.api.containers.assert_called_once_with(all=True)
    sdk.api.inspect_container.assert_not_called()


def test_result_cursor_uses_stable_identity_and_cannot_cross_query_host_or_group() -> None:
    sdk = MagicMock()
    sdk.api.containers.return_value = [
        _row("c" * 64, "web", "ubuntu:1", {"com.docker.compose.project": "other"}),
        _row("b" * 64, "metrics", "Ubuntu:1", {"com.docker.compose.project": "commerce"}),
        _row("a" * 64, "api", "ubuntu:1", {"com.docker.compose.project": "commerce"}),
    ]
    parameters = {"q": "UBUNTU", "limit": "1", "group_kind": "compose", "group_name": "commerce"}
    with patch("docksight.adapters.outbound.docker.runtime.connect", return_value=sdk), _client() as api:
        first = api.get(PATH, params=parameters, headers=HEADERS).json()
        assert [row["id"] for row in first["items"]] == ["a" * 64]
        cursor = first["next_cursor"]
        second = api.get(PATH, params=parameters | {"before": cursor}, headers=HEADERS).json()
        assert [row["id"] for row in second["items"]] == ["b" * 64]
        assert second["next_cursor"] is None
        for path, override in [
            (PATH, {"q": "other"}),
            (PATH, {"group_name": "other"}),
            (PATH, {"group_kind": "swarm"}),
            (PATH.replace("/local/", "/remote/"), {}),
        ]:
            assert api.get(path, params=parameters | override | {"before": cursor}, headers=HEADERS).status_code == 422
    assert sdk.api.containers.call_count == 2


def test_swarm_search_matches_id_prefix_in_the_exact_namespace() -> None:
    sdk = MagicMock()
    sdk.api.containers.return_value = [
        _row("ab" + "0" * 62, "web", "ubuntu:1", {"com.docker.stack.namespace": "shop"}),
        _row("ab" + "1" * 62, "web", "ubuntu:1", {"com.docker.stack.namespace": "shopfront"}),
        _row("0" + "ab" + "1" * 61, "db", "alpine:1", {"com.docker.stack.namespace": "shop"}),
    ]
    with patch("docksight.adapters.outbound.docker.runtime.connect", return_value=sdk), _client() as api:
        result = api.get(PATH, params={"q": "AB", "group_kind": "swarm", "group_name": "shop"}, headers=HEADERS)

    assert result.status_code == 200
    assert [(row["name"], row["swarm_stack"]) for row in result.json()["items"]] == [("web", "shop")]


def test_compose_project_search_treats_punctuation_as_literal() -> None:
    sdk = MagicMock()
    sdk.api.containers.return_value = [
        _row("a" * 64, "web", "ubuntu:1", {"com.docker.compose.project": "prod.x"}),
        _row("b" * 64, "web", "ubuntu:1", {"com.docker.compose.project": "prodax"}),
    ]
    with patch("docksight.adapters.outbound.docker.runtime.connect", return_value=sdk), _client() as api:
        result = api.get(PATH, params={"q": "D.X"}, headers=HEADERS)

    assert result.status_code == 200
    assert [row["id"] for row in result.json()["items"]] == ["a" * 64]


def test_search_finds_an_unnamed_dead_container_by_id() -> None:
    identity = "ab" + "0" * 62
    sdk = MagicMock()
    sdk.api.containers.return_value = [_row(identity, "unused", "ubuntu:1") | {"Names": [], "State": "dead"}]
    with patch("docksight.adapters.outbound.docker.runtime.connect", return_value=sdk), _client() as api:
        result = api.get(PATH, params={"q": "AB"}, headers=HEADERS)

    assert result.status_code == 200
    assert [(row["id"], row["name"], row["state"]) for row in result.json()["items"]] == [(identity, identity, "dead")]


def test_id_fallback_does_not_match_as_an_observed_name() -> None:
    unnamed_id = "1" * 58 + "abcdef"
    named_id = "2" * 58 + "abcdef"
    sdk = MagicMock()
    sdk.api.containers.return_value = [
        _row(unnamed_id, "unused", "ubuntu:1") | {"Names": [], "State": "dead"},
        _row(named_id, named_id, "ubuntu:1"),
    ]
    with patch("docksight.adapters.outbound.docker.runtime.connect", return_value=sdk), _client() as api:
        result = api.get(PATH, params={"q": "ABCD"}, headers=HEADERS)

    assert result.status_code == 200
    assert [(row["id"], row["name"]) for row in result.json()["items"]] == [(named_id, named_id)]


def test_search_uses_the_canonical_container_name_after_a_link_alias() -> None:
    sdk = MagicMock()
    sdk.api.containers.return_value = [
        _row("a" * 64, "worker", "ubuntu:1") | {"Names": ["/frontend/upstream", "/worker"]},
    ]
    with patch("docksight.adapters.outbound.docker.runtime.connect", return_value=sdk), _client() as api:
        result = api.get(PATH, params={"q": "worker"}, headers=HEADERS)

    assert result.status_code == 200
    assert [row["name"] for row in result.json()["items"]] == ["worker"]


@pytest.mark.parametrize(
    "invalid_field", [{"Names": "worker"}, {"Names": [5]}, {"Image": []}, {"State": "unrecognized"}]
)
def test_malformed_docker_summaries_fail_without_exposing_raw_values(invalid_field: dict[str, object]) -> None:
    sdk = MagicMock()
    sdk.api.containers.return_value = [_row("a" * 64, "worker", "ubuntu:1") | invalid_field]
    with patch("docksight.adapters.outbound.docker.runtime.connect", return_value=sdk), _client() as api:
        result = api.get(PATH, params={"q": "worker"}, headers=HEADERS)

    assert result.status_code == 502
    assert result.json()["code"] == "invalid_runtime_data"
    assert "unrecognized" not in result.text


@pytest.mark.parametrize(
    "parameters",
    [
        {"q": " "},
        {"q": "x" * 129},
        {"q": "worker", "limit": "51"},
        {"q": "worker", "group_kind": "compose"},
        {"q": "worker", "group_name": "commerce"},
        {"q": "worker", "before": "invalid"},
    ],
)
def test_invalid_search_is_rejected_before_docker_access(parameters: dict[str, str]) -> None:
    with patch("docksight.adapters.outbound.docker.runtime.connect") as connect, _client() as api:
        assert api.get(PATH, params=parameters, headers=HEADERS).status_code == 422
    connect.assert_not_called()


def test_search_requires_authentication_and_a_configured_host() -> None:
    with patch("docksight.adapters.outbound.docker.runtime.connect") as connect, _client() as api:
        assert api.get(PATH, params={"q": "web"}).status_code == 401
        assert api.get(PATH.replace("/local/", "/unknown/"), params={"q": "web"}, headers=HEADERS).status_code == 404
    connect.assert_not_called()


def test_inspect_keeps_accepting_a_container_named_search() -> None:
    sdk = MagicMock()
    sdk.api.inspect_container.return_value = {
        "Id": "a" * 64,
        "Name": "/search",
        "Config": {"Image": "ubuntu:1", "Env": [], "Labels": {}},
        "State": {"Status": "running"},
    }
    with patch("docksight.adapters.outbound.docker.runtime.connect", return_value=sdk), _client() as api:
        result = api.get("/api/v1/hosts/local/containers/search", headers=HEADERS)

    assert result.status_code == 200
    assert (result.json()["id"], result.json()["name"]) == ("a" * 64, "search")
    sdk.api.inspect_container.assert_called_once_with("search")
