import re
from typing import Final

_SECRET_NAME: Final = re.compile(
    r"secret|password|passwd|token|credential|private|api.?key|dsn|database_url|(^|_)key($|_)", re.I
)
_PRIVATE_KEY: Final = re.compile(
    r"-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
    re.S,
)
_ASSIGNMENT: Final = re.compile(
    r"(?i)((?:password|passwd|secret|token|api[_-]?key|authorization)\s*[=:]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
)
_URL_AUTH: Final = re.compile(r"(\w+://)[^\s/@:]+:[^\s/@]+@")
_TOKEN: Final = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{16,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b"
)


def secret_name(name: str) -> bool:
    return bool(_SECRET_NAME.search(name))


class Redactor:
    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        self.secrets = tuple(sorted({value for value in secrets if value}, key=len, reverse=True))

    def with_environment(self, environment: list[str]) -> "Redactor":
        values = tuple(
            value
            for entry in environment
            for key, separator, value in [entry.partition("=")]
            if separator and secret_name(key)
        )

        return Redactor((*self.secrets, *values))

    def text(self, value: str) -> str:
        value = _PRIVATE_KEY.sub("[REDACTED]", value)
        value = _URL_AUTH.sub(r"\1[REDACTED]@", value)
        value = _ASSIGNMENT.sub(r"\1[REDACTED]", value)
        value = _TOKEN.sub("[REDACTED]", value)
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")

        return value
