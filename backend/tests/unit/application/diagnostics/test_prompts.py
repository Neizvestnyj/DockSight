from docksight.application.diagnostics.prompts import final_prompt


def test_finalization_requires_russian_prose_for_a_russian_operator_question() -> None:
    prompt = final_prompt("Что случилось с vintoria-infra?")  # noqa: RUF001
    assert "Write summary, cause.immediate, cause.underlying, cause.unknowns, and action_reason in Russian" in prompt
    assert "Do not translate log entries" in prompt


def test_finalization_keeps_english_questions_in_english() -> None:
    assert "in English" in final_prompt("What happened to infra?")
