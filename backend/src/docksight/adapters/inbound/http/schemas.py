from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, StrictBool, model_validator

from docksight.application.views.schemas import Contract, GroupTarget
from docksight.domain.actions import Operation

type HostId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
type ContainerId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")]


class ChatTurn(Contract):
    """Accept a diagnostic query scoped to one host and optional session."""

    host: HostId
    query: str = Field(min_length=1, max_length=4000)
    session_id: UUID | None = None
    group: GroupTarget | None = None
    container_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def single_target(self) -> Self:
        """Reject conflicting explicit scopes rather than silently preferring one resource."""
        if self.group is not None and self.container_id is not None:
            raise ValueError("Choose either a group or an exact container")
        return self


class ActionPrepare(Contract):
    """Identify the exact container and operation to prepare."""

    host: HostId
    container_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    operation: Operation


class ActionExecute(Contract):
    """Carry the caller's explicit confirmation of a prepared action."""

    confirmed: StrictBool
