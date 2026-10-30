from typing import Final

from pydantic import TypeAdapter

from docksight.domain.diagnostics import JsonObject, JsonValue
from docksight.domain.errors import DockSightError

_OBJECT: Final = TypeAdapter(JsonObject)
_UNSUPPORTED: Final = {
    "default",
    "title",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "pattern",
}


def parse_object(value: object) -> JsonObject:
    """Decode a JSON object and reject non-object response values."""
    return _OBJECT.validate_json(value) if isinstance(value, (str, bytes)) else _OBJECT.validate_python(value)


def provider_error(status: int) -> DockSightError:
    """Map an HTTP provider status to a safe public domain error."""
    if status == 429:
        return DockSightError("provider_rate_limit", "Model provider rate limit reached", 429)
    if status == 404:
        return DockSightError(
            "model_unavailable",
            "The configured model was not found or is unavailable to this API key. "
            "Check the model name and your access.",
            422,
        )
    if status in {400, 422}:
        return DockSightError(
            "model_not_supported",
            "Model request rejected; verify model capabilities and configuration",
            422,
        )
    if status in {401, 403}:
        return DockSightError("provider_authentication", "Model provider authentication failed", 502)

    return DockSightError("provider_unavailable", "Model provider is unavailable", 503)


def strict_schema(schema: JsonObject) -> JsonObject:
    """Convert nullable optional fields into the provider's required strict schema."""
    return parse_object(_strict_value(schema))


def _strict_value(value: JsonValue) -> JsonValue:
    """Recursively normalize schema objects without changing the original contract."""
    if isinstance(value, list):
        return [_strict_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _strict_value(item) for key, item in value.items() if key not in _UNSUPPORTED}
    if result.get("type") == "object":
        properties = result.get("properties", {})
        result["additionalProperties"] = False
        if isinstance(properties, dict):
            result["required"] = list(properties)

    return result
