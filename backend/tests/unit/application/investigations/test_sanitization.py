import pytest

from docksight.application.investigations.contracts import WorkspacePatch
from docksight.application.investigations.sanitization import sanitized_target, sanitized_workspace
from docksight.application.redaction import Redactor
from docksight.application.views.schemas import ContainerTarget
from docksight.domain.errors import DockSightError


def test_sanitizing_display_labels_preserves_exact_id_and_explicit_patch_fields() -> None:
    target = ContainerTarget(id="a" * 64, name="synthetic-secret")
    patch = WorkspacePatch(expected_revision=7, selected_container=target)
    safe = sanitized_workspace(patch, Redactor(secrets=("synthetic-secret",)))
    assert safe.model_fields_set == patch.model_fields_set
    assert safe.selected_container == ContainerTarget(id=target.id, name="[REDACTED]")
    assert target.name == "synthetic-secret"


def test_redaction_expansion_beyond_display_label_bound_returns_typed_input_error() -> None:
    target = ContainerTarget(id="a" * 64, name="token=x " * 32)
    with pytest.raises(DockSightError) as caught:
        sanitized_target(target, Redactor())
    assert caught.value.code == "invalid_target"
    assert "token=x" not in caught.value.message
