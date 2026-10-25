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
    return (
        _OBJECT.validate_json(value)
        if isinstance(value, (str, bytes))
        else _OBJECT.validate_python(value)
    )


def provider_error(status: int) -> DockSightError:
    if status == 429:
        return DockSightError("provider_rate_limit", "Model provider rate limit reached", 429)
    if status in {400, 404, 422}:
        return DockSightError(
            "model_not_supported",
            "Model request rejected; verify model capabilities and configuration",
            422,
        )
    if status in {401, 403}:
        return DockSightError(
            "provider_authentication", "Model provider authentication failed", 502
        )

    return DockSightError("provider_unavailable", "Model provider is unavailable", 503)


def strict_schema(schema: JsonObject) -> JsonObject:
    def visit(value: JsonValue) -> JsonValue:
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: visit(item) for key, item in value.items() if key not in _UNSUPPORTED}
        if result.get("type") == "object":
            properties = result.get("properties", {})
            result["additionalProperties"] = False
            if isinstance(properties, dict):
                result["required"] = list(properties)

        return result

    return parse_object(visit(schema))
