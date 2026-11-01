from typing import Final, cast

from pydantic import TypeAdapter

from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.views.schemas import DiagnosisProposal, Widget
from docksight.domain.diagnostics import JsonObject

_WIDGETS: Final = TypeAdapter(Widget)


def proposal_schema(context: EvidenceContext | None = None) -> JsonObject:
    """Offer only collected references and card types backed by this turn's owned observations."""
    schema = cast(JsonObject, DiagnosisProposal.model_json_schema())
    if context is None:
        return schema
    evidence_ids = list(context.evidence)
    definitions = cast(dict[str, JsonObject], schema["$defs"])
    for definition in [schema, *definitions.values()]:
        properties = cast(JsonObject, definition.get("properties", {}))
        references = properties.get("evidence_ids")
        if not isinstance(references, dict):
            continue
        references["items"] = {"type": "string", "enum": list(evidence_ids)} if evidence_ids else {"type": "string"}
        if not evidence_ids:
            references["maxItems"] = 0
    _constrain_widgets(schema, definitions["WidgetProposal"], context)
    return schema


def _constrain_widgets(schema: JsonObject, definition: JsonObject, context: EvidenceContext) -> None:
    """Match selectable cards to the typed data required by server assembly."""
    supported = {
        "container_status": bool(context.snapshots),
        "log_anomalies": bool(context.logs.keys() & context.snapshots.keys()),
        "compose_stack": bool(context.stacks),
        "env_inspector": bool(context.snapshots),
    }
    properties = cast(dict[str, JsonObject], definition["properties"])
    if any(supported.values()):
        properties["widget_type"]["enum"] = [kind for kind, available in supported.items() if available]
    else:
        cast(dict[str, JsonObject], schema["properties"])["widgets"] = {
            "type": "null",
            "description": "No card data is available; use null.",
        }


def widget_schema() -> JsonObject:
    """Resolve a public widget schema from the allowlisted registry."""
    return {"schema_version": 1, "widgets": cast(JsonObject, _WIDGETS.json_schema())}
