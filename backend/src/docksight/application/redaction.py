import re
from typing import Final

_SECRET_NAME: Final = re.compile(
    r"secret|password|passwd|token|credential|private|api.?key|dsn|database_url|(^|_)key($|_)", re.I
)
_PRIVATE_KEY: Final = re.compile(
    r"-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
    re.S,
)
_QUOTED: Final = r"\"(?:\\[^\r\n]|[^\"\\\r\n])*\"|'(?:\\[^\r\n]|[^'\\\r\n])*'"
_ASSIGNMENT: Final = re.compile(
    r"(?i)((?:password|passwd|secret|token|api[_-]?key)[\"']?[ \t]*[=:][ \t]*)"
    rf"({_QUOTED}|Bearer[ \t]+[^\s,;]+|[^\s,;]+)",
)
_AUTHORIZATION: Final = re.compile(
    r"(?i)(authorization[\"']?[ \t]*[=:][ \t]*)" rf"({_QUOTED}|[^\r\n]+)",
)
_URL_AUTH: Final = re.compile(r"(\w+://)[^\s/@:]+:[^\s/@]+@")
_TOKEN: Final = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{16,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b"
)


def secret_name(name: str) -> bool:
    """Identify environment or field names that may contain credentials."""
    return bool(_SECRET_NAME.search(name))


def _mask_assignment(match: re.Match[str]) -> str:
    """Replace a credential assignment while retaining its recognizable key."""
    value = match.group(2)
    replacement = "[REDACTED]"
    if value[0] in {'"', "'"}:
        replacement = f"{value[0]}{replacement}{value[0]}"

    return match.group(1) + replacement


class Redactor:
    """Remove configured secrets and common credential patterns from untrusted text."""

    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        """Retain non-empty secret values for exact replacement."""
        self.secrets = tuple(sorted({value for value in secrets if value}, key=len, reverse=True))

    def with_environment(self, environment: list[str]) -> "Redactor":
        """Extend secret values using sensitive container environment entries."""
        values = tuple(
            value
            for entry in environment
            for key, separator, value in [entry.partition("=")]
            if separator and secret_name(key)
        )

        return Redactor((*self.secrets, *values))

    def text(self, value: str) -> str:
        """Redact credentials, private keys, connection passwords, and control sequences."""
        value = _PRIVATE_KEY.sub("[REDACTED]", value)
        value = _URL_AUTH.sub(r"\1[REDACTED]@", value)
        value = _AUTHORIZATION.sub(_mask_assignment, value)
        value = _ASSIGNMENT.sub(_mask_assignment, value)
        value = _TOKEN.sub("[REDACTED]", value)
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")

        return value
