import pytest

from docksight.application.redaction import Redactor


@pytest.mark.parametrize(
    "text",
    [
        '{"password": "private-sentinel", "status": "failed"}',
        "Authorization: Bearer private-sentinel",
        "api_key='private-sentinel'",
    ],
)
def test_json_and_header_credentials_are_redacted(text: str) -> None:
    result = Redactor().text(text)
    assert "private-sentinel" not in result
    assert "[REDACTED]" in result
