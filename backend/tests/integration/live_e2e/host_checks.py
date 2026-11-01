from collections.abc import Mapping

from docker.models.containers import Container

from docksight.application.views.schemas import (
    ComposeStackCard,
    ContainerStatusCard,
    DiagnosisResponse,
    GroupLogResult,
    HostInspection,
    LogAnomalyCard,
)
from tests.integration.live_e2e.lab import ComposeLab


def check_host(answer: DiagnosisResponse, lab: ComposeLab) -> None:
    """Compare the bounded overview to Docker facts across owned projects and an ungrouped failure."""
    overview = answer.host_overview
    assert overview is not None and answer.group is None
    containers = {row.id: row for row in (*lab.containers.values(), *lab.peers.values(), *lab.standalone.values())}
    assert lab.peers and lab.standalone
    assert (overview.host, overview.total, overview.truncated, overview.discovery_code) == (
        "e2e",
        len(containers),
        False,
        None,
    )
    assert overview.running == sum(row.attrs["State"]["Status"] == "running" for row in containers.values())
    failed = {key for key, row in containers.items() if row.attrs["State"]["Status"] == "exited"}
    assert overview.attention == len(failed)
    assert {row.container_id for row in overview.members} == containers.keys()
    assert {(row.kind, row.name) for row in overview.targets} == {
        ("compose", lab.project),
        ("compose", lab.peer_project),
    }
    references = {row.id: row for row in answer.evidence}
    primary = references[overview.evidence_id]
    assert (primary.kind, primary.host, primary.container_id) == ("host", "e2e", None)
    _check_members(answer, containers, failed)
    _check_logs(answer, failed)
    _check_widgets(answer, set(containers))


def _check_members(answer: DiagnosisResponse, containers: Mapping[str, Container], failed: set[str]) -> None:
    """Require each host row to reproduce its actual identity, state, health and canonical group."""
    assert answer.host_overview is not None
    for member in answer.host_overview.members:
        observed = containers[member.container_id]
        state = observed.attrs["State"]
        assert (member.name, member.state, member.exit_code, member.oom_killed, member.restart_count) == (
            observed.name,
            state["Status"],
            state["ExitCode"],
            state["OOMKilled"],
            observed.attrs["RestartCount"],
        )
        assert member.health == state.get("Health", {}).get("Status")
        expected_project = observed.labels.get("com.docker.compose.project")
        if expected_project is None:
            assert member.group is None
        else:
            assert member.group is not None
            assert (member.group.kind, member.group.name) == ("compose", expected_project)
        assert member.attention is (member.container_id in failed)


def _check_logs(answer: DiagnosisResponse, failed: set[str]) -> None:
    """Require one host-wide log budget, exact evidence provenance and retained server detail cards."""
    assert answer.host_overview is not None
    collected = _check_log_coverage(answer.host_overview, failed)
    references = {row.id: row for row in answer.evidence}
    for result in collected:
        assert result.evidence_id is not None
        reference = references[result.evidence_id]
        assert (reference.kind, reference.container_id) == ("logs", result.container_id)
    collected_ids = {row.container_id for row in collected}
    assert collected_ids <= {row.snapshot.id for row in answer.widgets if isinstance(row, ContainerStatusCard)}
    assert collected_ids <= {row.container_id for row in answer.widgets if isinstance(row, LogAnomalyCard)}


def _check_log_coverage(overview: HostInspection, failed: set[str]) -> list[GroupLogResult]:
    """Require explicit skipped coverage while accepting a later successful model-requested fifth read."""
    results = overview.logs
    assert {row.container_id for row in results} == failed
    assert len(results) == len(failed)
    collected = [row for row in results if row.state == "collected"]
    assert min(4, len(failed)) <= len(collected) <= len(failed)
    names = {row.container_id: row.name for row in overview.members}
    for result in results:
        assert result.name == names[result.container_id]
        if result.state != "collected":
            assert (result.state, result.code, result.evidence_id) == ("not_collected", "host_log_limit", None)
    return collected


def _check_widgets(answer: DiagnosisResponse, ids: set[str]) -> None:
    """Reject foreign host, container and group cards even when their own references are syntactically valid."""
    assert answer.host_overview is not None
    targets = {(row.kind, row.name) for row in answer.host_overview.targets}
    for card in answer.widgets:
        if isinstance(card, ComposeStackCard):
            assert card.host == "e2e"
            assert all((row.kind, row.name) in targets for row in card.stacks)
        elif isinstance(card, ContainerStatusCard):
            _check_status(card, answer, ids)
        else:
            assert card.host == "e2e" and card.container_id in ids


def _check_status(card: ContainerStatusCard, answer: DiagnosisResponse, ids: set[str]) -> None:
    """Keep a status card's exact identity aligned with its source observations."""
    references = {row.id: row for row in answer.evidence}
    assert card.snapshot.id in ids and card.snapshot.host == "e2e"
    assert card.evidence_ids
    assert all(references[ref].container_id in {None, card.snapshot.id} for ref in card.evidence_ids)
    assert answer.host_overview is not None
    member = next(row for row in answer.host_overview.members if row.container_id == card.snapshot.id)
    assert (card.snapshot.state, card.snapshot.exit_code, card.snapshot.oom_killed, card.snapshot.restart_count) == (
        member.state,
        member.exit_code,
        member.oom_killed,
        member.restart_count,
    )
    assert card.snapshot.health == member.health
