from uuid import uuid4

import pytest

from docksight.adapters.outbound.memory.investigations import MemoryInvestigations
from docksight.application.investigations.contracts import ActorWorkspacePatch, QuestionTurn, StartTurn, WorkspacePatch
from docksight.application.investigations.lifecycle import input_digest
from docksight.application.investigations.service import Investigations
from docksight.application.model_catalog import ModelSelection
from docksight.application.redaction import Redactor
from docksight.domain.errors import DockSightError


async def test_configured_scope_redacted_workspace_and_owned_archive_operations() -> None:
    hosts = {"local"}
    service = Investigations(MemoryInvestigations(), lambda: hosts, Redactor(secrets=("top-secret",)))
    identity = str(uuid4())
    await service.create("alice", identity, "local")
    with pytest.raises(DockSightError):
        await service.create("alice", str(uuid4()), "unconfigured")
    saved = await service.patch_workspace("alice", identity, WorkspacePatch(expected_revision=0, draft="top-secret"))
    assert "top-secret" not in saved.draft and saved.revision == 1
    prefs = await service.patch_actor_workspace(
        "alice", ActorWorkspacePatch(expected_revision=0, host="local", last_investigation_id=identity)
    )
    assert await service.workspace("alice") == prefs
    assert (await service.list_owned("alice")).items[0].id == identity
    assert (await service.turns("alice", identity)).items == ()
    hosts.clear()
    assert (await service.read("alice", identity)).id == identity
    with pytest.raises(DockSightError):
        await service.patch_actor_workspace("alice", ActorWorkspacePatch(expected_revision=1, host="local"))
    with pytest.raises(DockSightError):
        await service.read("bob", identity)
    await service.delete("alice", identity)
    assert (await service.list_owned("alice")).items == ()


def test_digest_excludes_revisions_ids_and_defaults_but_preserves_logical_input() -> None:
    submitted = QuestionTurn(
        investigation_id=str(uuid4()), submission_id=str(uuid4()), expected_revision=0, query="  secret input  "
    )
    digest = input_digest(StartTurn(submitted))
    replay = submitted.model_copy(
        update={"expected_revision": 42, "submission_id": str(uuid4()), "query": "secret input"}
    )
    assert input_digest(StartTurn(replay)) == digest
    changed = submitted.model_copy(update={"model": ModelSelection(provider="configured", model="new")})
    assert input_digest(StartTurn(changed)) != digest
    assert input_digest(StartTurn(submitted.model_copy(update={"query": "changed"}))) != digest
    assert len(digest) == 64 and "secret" not in digest
