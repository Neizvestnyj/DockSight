from dataclasses import replace

import pytest

from docksight.application.diagnostics.scope import resolve_target
from docksight.application.views.schemas import GroupTarget
from docksight.domain.errors import DockSightError
from docksight.domain.runtime import StackSummary
from tests.fakes import FakeRuntime


@pytest.mark.parametrize("name", ["vintoria-infta", "vintoria-infar", "vintoria-infr", "vintoria-iinfra"])
async def test_unique_single_edit_project_reference_resolves_to_observed_identity(name: str) -> None:
    runtime = FakeRuntime()
    runtime.item = replace(runtime.item, compose_project="vintoria-infra")
    query = f"\u0427\u0442\u043e \u043d\u0435 \u0442\u0430\u043a \u0441 {name}?"
    resolved = await resolve_target(runtime, "local", query)
    assert resolved.group == GroupTarget(kind="compose", name="vintoria-infra")
    assert not runtime.mutations


async def test_similar_group_names_require_selection_instead_of_guessing() -> None:
    class SimilarGroups(FakeRuntime):
        """Expose a stack that is as close to the typo as the Compose project."""

        async def stacks(self, host: str, kind: str) -> tuple[StackSummary, ...]:
            """Return an observed competing stack identity."""
            return (StackSummary("vintoria-infra", "swarm", 2, 0),)

    runtime = SimilarGroups()
    runtime.item = replace(runtime.item, compose_project="vintoria-infra")
    with pytest.raises(DockSightError, match="ambiguous"):
        await resolve_target(runtime, "local", "Check vintoria-infta?")
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
