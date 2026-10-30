import json

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.diagnostics.prompts import final_prompt, group_catalog
from docksight.application.views.schemas import GroupTarget
from tests.fakes import snapshot


def test_final_prompt_catalog_identifies_current_evidence_without_repeating_untrusted_log_text() -> None:
    context = EvidenceContext()
    context.record("logs", "local", {"message": "untrusted-sql-error"}, snapshot=snapshot())
    prompt = final_prompt("Could the database be stopped?", context)
    catalog = json.loads(prompt.rsplit("\n", 1)[-1])
    assert catalog == [{"id": "e1", "kind": "logs", "container_id": "a" * 64}]
    assert "untrusted-sql-error" not in prompt


def test_group_catalog_bounds_names_without_hiding_omitted_candidates() -> None:
    candidates = tuple(GroupTarget(kind="compose", name=f"project-{index}") for index in range(33))
    catalog = json.loads(group_catalog(candidates))
    assert catalog["truncated"] is True
    assert len(catalog["available_groups"]) == 32
    assert catalog["available_groups"] == [row.model_dump() for row in candidates[:32]]


def test_explicit_answer_language_overrides_transliterated_names() -> None:
    assert "in English" in final_prompt("What is wrong with винтория инфра? Please answer in English.")
    assert "in English" in final_prompt("Что случилось? Ответь на английском.")
    assert "in Russian" in final_prompt("What happened? Please answer in Russian.")


def test_finalization_requires_russian_prose_for_a_russian_operator_question() -> None:
    prompt = final_prompt("Что случилось с vintoria-infra?")  # noqa: RUF001
    assert "Write summary, cause.immediate, cause.underlying, cause.unknowns, and action_reason in Russian" in prompt
    assert "Do not translate log entries" in prompt


def test_finalization_keeps_english_questions_in_english() -> None:
    assert "in English" in final_prompt("What happened to infra?")
