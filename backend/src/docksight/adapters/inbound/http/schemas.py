from typing import Annotated
from uuid import UUID

from pydantic import Field, StrictBool

from docksight.application.views.schemas import Contract
from docksight.domain.actions import Operation

type HostId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
type ContainerId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")]


class ChatTurn(Contract):
    """Accept a diagnostic query scoped to one host and optional session."""

    host: HostId
    query: str = Field(min_length=1, max_length=4000)
    session_id: UUID | None = None


class ActionPrepare(Contract):
    """Identify the exact container and operation to prepare."""

    host: HostId
    container_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    operation: Operation


class ActionExecute(Contract):
    """Carry the caller's explicit confirmation of a prepared action."""

    confirmed: StrictBool
