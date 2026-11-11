from collections.abc import AsyncGenerator
from uuid import uuid4

from docksight.application.diagnostics.use_case import Diagnostics
from docksight.application.events import TurnEvent
from docksight.application.investigations.contracts import DiagnosticCommand
from docksight.application.model_catalog import ModelSelection
from docksight.application.ports.models import ModelMessage
from docksight.application.views.schemas import ContainerTarget, GroupTarget


def diagnostic_stream(
    service: Diagnostics,
    actor: str,
    host: str,
    query: str,
    investigation_id: str | None = None,
    group: GroupTarget | None = None,
    container_id: str | None = None,
    *,
    context: tuple[ModelMessage, ...] = (),
) -> AsyncGenerator[TurnEvent]:
    """Exercise preallocated diagnostic commands directly without creating a legacy session store."""
    identity = service.model_identity
    return service.run(
        DiagnosticCommand(
            turn_id=str(uuid4()),
            investigation_id=investigation_id or str(uuid4()),
            actor=actor,
            host=host,
            query=service.redactor.text(query),
            target=group or (ContainerTarget(id=container_id, name=container_id) if container_id else None),
            identity=ModelSelection(provider=identity[0], model=identity[1]) if identity else None,
            context=context,
        )
    )
