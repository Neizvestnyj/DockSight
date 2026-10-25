from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from docksight.application.ports.models import ModelMessage
from docksight.domain.actions import PreparedAction
from docksight.domain.diagnostics import JsonObject


@dataclass
class Session:
    """Retain conversation history bound to one actor and configured host."""

    id: str
    actor: str
    host: str
    history: list[ModelMessage] = field(default_factory=list[ModelMessage])


class SessionStore(Protocol):
    """Define scoped session retention and exclusive turn ownership."""

    def lease(
        self,
        session_id: str | None,
        actor: str,
        host: str,
    ) -> AbstractAsyncContextManager[Session]:
        """Lease an existing scoped session or create one for this actor and host."""
        ...


class ActionStore(Protocol):
    """Define atomic action claims and serialization of exact-container mutations."""

    async def add(self, action: PreparedAction) -> None:
        """Retain a newly prepared action within storage capacity."""
        ...

    async def get(self, action_id: str, actor: str) -> PreparedAction:
        """Resolve an action only within its actor's scope."""
        ...

    async def claim(
        self,
        action_id: str,
        actor: str,
        key: str,
        confirmed: bool,
        now: datetime,
    ) -> tuple[PreparedAction, bool]:
        """Atomically validate confirmation, expiry, ownership, and idempotency."""
        ...

    def target_lock(self, host: str, container_id: str) -> AbstractAsyncContextManager[None]:
        """Hold exclusive mutation access to one host/container pair."""
        ...

    async def block_target(self, host: str, container_id: str) -> None:
        """Reject future mutations for a target with an unknown prior outcome."""
        ...


class AuditPort(Protocol):
    """Define emission of sanitized action audit events."""

    async def record(self, event: str, data: JsonObject) -> None:
        """Record an action event or raise when the audit output is unavailable."""
        ...


type EventStream = AsyncIterator[JsonObject]
