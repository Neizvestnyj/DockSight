from collections.abc import Sequence
from typing import Final, cast

from pydantic import TypeAdapter

from docksight.application.views.schemas import DiagnosisProposal, Widget
from docksight.domain.diagnostics import JsonObject

_WIDGETS: Final = TypeAdapter(Widget)


def proposal_schema(evidence_ids: Sequence[str] | None = None) -> JsonObject:
    """Constrain final and repair references to this turn while keeping runtime fields server-owned."""
    schema = cast(JsonObject, DiagnosisProposal.model_json_schema())
    if evidence_ids is None:
        return schema
    definitions = cast(dict[str, JsonObject], schema["$defs"])
    for definition in [schema, *definitions.values()]:
        properties = cast(JsonObject, definition.get("properties", {}))
        references = properties.get("evidence_ids")
        if not isinstance(references, dict):
            continue
        references["items"] = {"type": "string", "enum": list(evidence_ids)} if evidence_ids else {"type": "string"}
        if not evidence_ids:
            references["maxItems"] = 0
    return schema


def widget_schema() -> JsonObject:
    """Resolve a public widget schema from the allowlisted registry."""
    return {"schema_version": 1, "widgets": cast(JsonObject, _WIDGETS.json_schema())}
