from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from docksight.adapters.outbound.memory.actions import MemoryActions
from docksight.adapters.outbound.memory.browser_sessions import MemoryBrowserSessions
from docksight.adapters.outbound.memory.transient import TransientInvestigations
from docksight.adapters.outbound.memory.turns import MemoryTurnStore
from docksight.adapters.outbound.persistence.actions import SQLiteActions
from docksight.adapters.outbound.persistence.browser_sessions import (
    SQLiteBrowserSessions,
)
from docksight.adapters.outbound.persistence.database import PersistentDatabase
from docksight.adapters.outbound.persistence.investigations import SQLiteInvestigations
from docksight.adapters.outbound.persistence.recovery import (
    browser_session_recovery,
    recover_actions,
    recover_investigations,
)
from docksight.adapters.outbound.persistence.turns import SQLiteTurnStore
from docksight.application.browser_sessions import credential_fingerprints
from docksight.application.investigations.ports import InvestigationArchive, TurnStore
from docksight.application.ports.browser_sessions import BrowserSessionStore
from docksight.application.ports.state import ActionStore

if TYPE_CHECKING:
    from docksight.bootstrap import Settings


@dataclass(frozen=True)
class StateAdapters:
    """Share one storage lifetime across history, action protection, and browser sessions."""

    archive: InvestigationArchive
    turns: TurnStore
    actions: ActionStore
    browser_sessions: BrowserSessionStore
    database: PersistentDatabase | None = None


def build_state(
    settings: Settings,
    archive: InvestigationArchive | None = None,
    turns: TurnStore | None = None,
    actions: ActionStore | None = None,
    browser_sessions: BrowserSessionStore | None = None,
) -> StateAdapters:
    """Keep fully explicit stores isolated while sharing one owner for configured default adapters."""
    if (archive is None) != (turns is None):
        raise ValueError("Archive and turn stores must be supplied together")
    if archive is not None and turns is not None and actions is not None and browser_sessions is not None:
        return StateAdapters(archive, turns, actions, browser_sessions)
    defaults = _default_state(settings)
    return StateAdapters(
        archive if archive is not None else defaults.archive,
        turns if turns is not None else defaults.turns,
        actions if actions is not None else defaults.actions,
        browser_sessions if browser_sessions is not None else defaults.browser_sessions,
        defaults.database,
    )


def _default_state(settings: Settings) -> StateAdapters:
    """Construct adapters without opening storage or performing external recovery work."""
    if settings.state_backend == "memory":
        archive = TransientInvestigations(settings.max_sessions, settings.state_ttl)
        return StateAdapters(
            archive,
            MemoryTurnStore(archive),
            MemoryActions(settings.max_actions, settings.state_ttl),
            MemoryBrowserSessions(),
        )
    recover_sessions = browser_session_recovery(
        credential_fingerprints(settings.api_credentials()),
        settings.browser_session_idle_ttl,
    )
    database = PersistentDatabase(settings.state_path, (recover_actions, recover_investigations, recover_sessions))
    return StateAdapters(
        SQLiteInvestigations(database),
        SQLiteTurnStore(database),
        SQLiteActions(database, settings.max_actions),
        SQLiteBrowserSessions(database),
        database,
    )
