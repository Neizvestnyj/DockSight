from pydantic import ValidationError

from docksight.application.investigations.contracts import Target, WorkspacePatch
from docksight.application.redaction import Redactor
from docksight.application.views.schemas import ContainerTarget
from docksight.domain.errors import DockSightError, ErrorKind


def sanitized_target(target: Target | None, redactor: Redactor) -> Target | None:
    """Redact display labels while refusing to change an exact group lookup identity."""
    if target is None:
        return None
    name = redactor.text(target.name)
    if not isinstance(target, ContainerTarget):
        if name != target.name:
            raise DockSightError("invalid_target", "Target identity contains sensitive text", ErrorKind.VALIDATION)
        return target.model_copy(deep=True)
    try:
        return ContainerTarget.model_validate(target.model_dump() | {"name": name})
    except ValidationError as error:
        raise DockSightError(
            "invalid_target", "Sanitized target label exceeds supported bounds", ErrorKind.VALIDATION
        ) from error


def sanitized_workspace(patch: WorkspacePatch, redactor: Redactor) -> WorkspacePatch:
    """Validate only explicitly supplied sanitized values before entering a storage transaction."""
    values = patch.model_dump(exclude_unset=True)
    if "draft" in patch.model_fields_set:
        values["draft"] = redactor.text(patch.draft)
    if "target" in patch.model_fields_set:
        values["target"] = sanitized_target(patch.target, redactor)
    if "selected_container" in patch.model_fields_set:
        values["selected_container"] = sanitized_target(patch.selected_container, redactor)
    try:
        return WorkspacePatch.model_validate(values)
    except ValidationError as error:
        raise DockSightError(
            "invalid_workspace", "Sanitized workspace exceeds supported bounds", ErrorKind.VALIDATION
        ) from error
