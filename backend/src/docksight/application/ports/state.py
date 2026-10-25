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
    id: str
    actor: str
    host: str
    history: list[ModelMessage] = field(default_factory=list[ModelMessage])


class SessionStore(Protocol):
    def lease(
        self,
        session_id: str | None,
        actor: str,
        host: str,
    ) -> AbstractAsyncContextManager[Session]: ...


class ActionStore(Protocol):
    async def add(self, action: PreparedAction) -> None: ...
    async def get(self, action_id: str, actor: str) -> PreparedAction: ...
    async def claim(
        self,
        action_id: str,
        actor: str,
        key: str,
        confirmed: bool,
        now: datetime,
    ) -> tuple[PreparedAction, bool]: ...
    def target_lock(self, host: str, container_id: str) -> AbstractAsyncContextManager[None]: ...
    async def block_target(self, host: str, container_id: str) -> None: ...


class AuditPort(Protocol):
    async def record(self, event: str, data: JsonObject) -> None: ...


type EventStream = AsyncIterator[JsonObject]
