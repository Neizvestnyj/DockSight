from typing import Final, cast

from pydantic import TypeAdapter

from docksight.application.views.schemas import DiagnosisProposal, Widget
from docksight.domain.diagnostics import JsonObject

_WIDGETS: Final = TypeAdapter(Widget)


def proposal_schema() -> JsonObject:
    """Return the model-facing diagnosis schema without authoritative runtime fields."""
    return cast(JsonObject, DiagnosisProposal.model_json_schema())


def widget_schema() -> JsonObject:
    """Resolve a public widget schema from the allowlisted registry."""
    return {"schema_version": 1, "widgets": cast(JsonObject, _WIDGETS.json_schema())}
