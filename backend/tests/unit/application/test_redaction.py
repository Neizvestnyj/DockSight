import json

import pytest

from docksight.application.redaction import Redactor


@pytest.mark.parametrize(
    "text",
    [
        '{"password": "private-sentinel", "status": "failed"}',
        "Authorization: Bearer private-sentinel",
        "Authorization: Basic private-sentinel",
        "aUtHoRiZaTiOn: bAsIc private-sentinel",
        '"Authorization": "Basic private-sentinel"',
        "'authorization': 'Basic private-sentinel'",
        'Authorization: Digest username="private-sentinel", response="another-secret"',
        "token=Bearer private-sentinel",
        "api_key: Bearer private-sentinel",
        "api_key='private-sentinel'",
    ],
)
def test_json_and_header_credentials_are_redacted(text: str) -> None:
    result = Redactor().text(text)
    assert "private-sentinel" not in result
    assert "[REDACTED]" in result


def test_authorization_redaction_preserves_adjacent_lines() -> None:
    result = Redactor().text("Authorization: Basic dXNlcjpwYXNzd29yZA==\nstatus=ready")
    assert result == "Authorization: [REDACTED]\nstatus=ready"


def test_empty_authorization_does_not_consume_the_next_line() -> None:
    assert Redactor().text("Authorization:\nstatus=ready") == "Authorization:\nstatus=ready"


def test_json_digest_credentials_with_escaped_quotes_are_fully_redacted() -> None:
    value = json.dumps(
        {
            "Authorization": 'Digest username="review-user", response="review-secret", realm="review-realm"',
            "status": "ready",
        }
    )
    result = Redactor().text("before=ready\r\n" + value + "\r\nafter=ready")
    before, encoded, after = result.split("\r\n")
    assert before == "before=ready"
    assert after == "after=ready"
    assert all(fragment not in result for fragment in ("review-user", "review-secret", "review-realm"))
    assert json.loads(encoded) == {"Authorization": "[REDACTED]", "status": "ready"}


@pytest.mark.parametrize("name", ["Authorization", "api_key"])
@pytest.mark.parametrize("delimiter", ['"', "'"])
def test_quoted_credentials_end_at_the_unescaped_matching_delimiter(name: str, delimiter: str) -> None:
    escaped_quote = "\\" + delimiter
    value = f"{name}: {delimiter}credential{escaped_quote}review-secret{delimiter}, status=ready\nnext=ready"
    result = Redactor().text(value)
    assert "review-secret" not in result
    assert result == f"{name}: {delimiter}[REDACTED]{delimiter}, status=ready\nnext=ready"
