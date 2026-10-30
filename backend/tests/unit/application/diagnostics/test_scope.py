from dataclasses import replace

import pytest

from docksight.application.diagnostics.scope import resolve_target
from docksight.application.views.schemas import GroupTarget
from docksight.domain.runtime import StackSummary
from tests.fakes import DiscoveryRuntime, FakeRuntime


@pytest.mark.parametrize(
    "query", ["Could vintoria-db simply be stopped?", "\u0410 может потому-что vintoria-db не запущен?"]
)
async def test_untyped_container_project_collision_offers_both_exact_resources(query: str) -> None:
    runtime = FakeRuntime()
    runtime.item = replace(runtime.item, name="vintoria-db", compose_project="vintoria-db")
    result = await resolve_target(runtime, "local", query)
    assert result.group is None and result.container_id is None
    assert result.selection is not None
    assert result.selection.model_dump() == {
        "candidates": [
            {"kind": "container", "id": "a" * 64, "name": "vintoria-db"},
            {"kind": "compose", "name": "vintoria-db"},
        ]
    }
    assert not runtime.mutations


async def test_explicit_compose_reference_disambiguates_a_container_project_collision() -> None:
    runtime = FakeRuntime()
    runtime.item = replace(runtime.item, name="vintoria-db", compose_project="vintoria-db")
    result = await resolve_target(runtime, "local", "Check Compose vintoria-db")
    assert result.group == GroupTarget(kind="compose", name="vintoria-db")
    assert result.selection is None and result.container_id is None


@pytest.mark.parametrize(
    "query",
    ["Что случилось?", "\u0410 что упало?", "Что не так?", "What happened?", "What's wrong?", "What failed?"],
)
async def test_unscoped_incident_questions_require_a_choice_between_observed_projects(query: str) -> None:
    result = await resolve_target(DiscoveryRuntime(), "local", query)
    assert result.group is None
    assert result.container_id is None
    assert result.selection is not None
    assert result.selection.candidates == [
        GroupTarget(kind="compose", name="other-project"),
        GroupTarget(kind="compose", name="vintoria-infra"),
    ]


@pytest.mark.parametrize(
    "query",
    [
        "Maybe the database is stopped? Check container vintoria-db.",
        "Может БД просто не запущена? Есть же контейнер vintoria-db",
        'Inspect the container named "vintoria-db"',
    ],
)
async def test_explicit_container_reference_wins_over_an_identically_named_project(query: str) -> None:
    runtime = FakeRuntime()
    runtime.item = replace(runtime.item, name="vintoria-db", compose_project="vintoria-db")
    result = await resolve_target(runtime, "local", query)
    assert result.group is None
    assert result.selection is None
    assert result.containers == (runtime.item,)
    assert result.container_id == runtime.item.id


@pytest.mark.parametrize("name", ["vintoria-infta", "vintoria-infar", "vintoria-infr", "vintoria-iinfra"])
async def test_unique_single_edit_project_reference_resolves_to_observed_identity(name: str) -> None:
    runtime = FakeRuntime()
    runtime.item = replace(runtime.item, compose_project="vintoria-infra")
    resolved = await resolve_target(runtime, "local", f"Что не так \u0441 {name}?")
    assert resolved.group == GroupTarget(kind="compose", name="vintoria-infra")
    assert not runtime.mutations


async def test_space_separated_canonical_name_resolves_without_expanding_a_prefix() -> None:
    runtime = FakeRuntime()
    runtime.item = replace(runtime.item, compose_project="vintoria-infra")
    resolved = await resolve_target(runtime, "local", "What happened to vintoria infra?")
    assert resolved.group == GroupTarget(kind="compose", name="vintoria-infra")
    assert (await resolve_target(runtime, "local", "What happened to vintoria?")).group is None


async def test_explicit_multi_container_question_does_not_silently_bind_the_first_container() -> None:
    result = await resolve_target(DiscoveryRuntime(), "local", "Compare container backend-1 and container grafana-1")
    assert result.group is None
    assert result.container_id is None


async def test_similar_group_names_require_selection_instead_of_guessing() -> None:
    class SimilarGroups(FakeRuntime):
        """Expose a stack that is as close to the typo as the Compose project."""

        async def stacks(self, host: str, kind: str) -> tuple[StackSummary, ...]:
            """Return an observed competing stack identity."""
            return (StackSummary("vintoria-infra", "swarm", 2, 0),)

    runtime = SimilarGroups()
    runtime.item = replace(runtime.item, compose_project="vintoria-infra")
    ambiguous = await resolve_target(runtime, "local", "Check vintoria-infta?")
    assert ambiguous.group is None
    assert ambiguous.selection is not None
    assert len(ambiguous.selection.candidates) == 2
    resolved = await resolve_target(runtime, "local", "Check Compose vintoria-infta?")
    assert resolved.group == GroupTarget(kind="compose", name="vintoria-infra")


@pytest.mark.parametrize("query", ["Check vintoria-backend-1", "Check other-project", "Check infra", "Check worker"])
async def test_near_matching_does_not_expand_container_names_or_unrelated_words(query: str) -> None:
    runtime = FakeRuntime()
    runtime.item = replace(runtime.item, compose_project="vintoria-infra")
    assert (await resolve_target(runtime, "local", query)).group is None


async def test_exact_container_identity_wins_over_a_near_group_name() -> None:
    runtime = FakeRuntime()
    runtime.item = replace(runtime.item, name="vintoria-infta", compose_project="vintoria-infra")
    assert (await resolve_target(runtime, "local", "Check vintoria-infta")).group is None


@pytest.mark.parametrize("label", ["bad label", "[REDACTED]", "x" * 129])
async def test_unrelated_invalid_project_labels_do_not_block_container_diagnosis(label: str) -> None:
    runtime = FakeRuntime()
    runtime.item = replace(runtime.item, compose_project=label)
    assert (await resolve_target(runtime, "local", "Check worker")).group is None


async def test_invalid_swarm_identity_does_not_hide_a_valid_observed_stack() -> None:
    class MalformedStack(FakeRuntime):
        """Expose a malformed unrelated label alongside a valid manager-owned namespace."""

        async def stacks(self, host: str, kind: str) -> tuple[StackSummary, ...]:
            """Keep malformed external metadata from masquerading as a contract-valid target."""
            return (StackSummary("[REDACTED]", "swarm", 1, 0), StackSummary("production", "swarm", 2, 0))

    resolved = await resolve_target(MalformedStack(), "local", "What happened to production?")
    assert resolved.group == GroupTarget(kind="swarm", name="production")


async def test_unresolved_cyrillic_question_retains_real_group_candidates_for_the_agent() -> None:
    result = await resolve_target(DiscoveryRuntime(), "local", "Что не так \u0441 винтория инфра?")
    assert result.group is None
    assert result.selection is None
    assert {row.name for row in result.candidates} == {"vintoria-infra", "other-project"}


async def test_colliding_names_return_typed_choices_instead_of_a_failed_diagnosis() -> None:
    class DualNamespace(DiscoveryRuntime):
        """Expose a real-name collision between different orchestration namespaces."""

        async def stacks(self, host: str, kind: str) -> tuple[StackSummary, ...]:
            """Add one Swarm candidate without changing observed Compose membership."""
            return (
                (StackSummary("vintoria-infra", "swarm", 1, 0),)
                if kind == "swarm"
                else await super().stacks(host, kind)
            )

    result = await resolve_target(DualNamespace(), "local", "What happened to vintoria-infra?")
    assert result.group is None
    assert result.selection is not None
    assert result.selection.candidates == [
        GroupTarget(kind="compose", name="vintoria-infra"),
        GroupTarget(kind="swarm", name="vintoria-infra"),
    ]
