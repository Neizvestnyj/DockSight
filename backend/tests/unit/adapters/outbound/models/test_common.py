import pytest

from docksight.adapters.outbound.models.common import provider_error, strict_schema
from docksight.application.diagnostics.context import EvidenceContext
from docksight.application.views.registry import proposal_schema


@pytest.mark.parametrize(
    "status,code,http_status",
    [
        (400, "model_not_supported", 422),
        (404, "model_unavailable", 422),
        (422, "model_not_supported", 422),
        (401, "provider_authentication", 502),
        (403, "provider_authentication", 502),
        (429, "provider_rate_limit", 429),
        (500, "provider_unavailable", 503),
    ],
)
def test_provider_status_distinguishes_missing_models_from_rejected_requests(
    status: int, code: str, http_status: int
) -> None:
    error = provider_error(status)
    assert (error.code, error.status) == (code, http_status)


def test_missing_model_explains_name_or_key_access_without_a_replacement_model() -> None:
    error = provider_error(404)
    assert error.message == (
        "The configured model was not found or is unavailable to this API key. Check the model name and your access."
    )


def test_no_card_schema_survives_provider_conversion_without_array_length_constraints() -> None:
    context = EvidenceContext()
    context.record("host", "local", {})
    schema = strict_schema(proposal_schema(context))
    assert schema["properties"]["widgets"]["type"] == "null"
