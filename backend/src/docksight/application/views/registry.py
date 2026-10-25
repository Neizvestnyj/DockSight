from typing import Final, cast

from pydantic import TypeAdapter

from docksight.application.views.schemas import DiagnosisProposal, Widget
from docksight.domain.diagnostics import JsonObject

_WIDGETS: Final = TypeAdapter(Widget)


def proposal_schema() -> JsonObject:
    return cast(JsonObject, DiagnosisProposal.model_json_schema())


def widget_schema() -> JsonObject:
    return {"schema_version": 1, "widgets": cast(JsonObject, _WIDGETS.json_schema())}
