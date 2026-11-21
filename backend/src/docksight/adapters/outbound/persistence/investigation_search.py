from datetime import datetime

from sqlalchemy import SQLColumnExpression, String, case, cast, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql.selectable import ScalarSelect

from docksight.adapters.outbound.persistence.codec import decode_cursor, encode_cursor, page_limit
from docksight.adapters.outbound.persistence.rows import InvestigationRow, TurnRow
from docksight.application.investigations.contracts import InvestigationSearchHit, InvestigationSearchPage
from docksight.application.investigations.search import question_match


def _contains_text(column: SQLColumnExpression[str], query: str) -> ColumnElement[bool]:
    """Treat SQLite wildcard characters as literal text and fold Unicode before comparing."""
    return func.instr(func.docksight_casefold(column), query) > 0


def _matching_turn(actor: str, query: str) -> ScalarSelect[str]:
    """Project the newest supported original question using the existing per-chat history index."""
    snapshot = case((func.json_valid(TurnRow.snapshot) == 1, TurnRow.snapshot), else_="{}")
    question = func.json_extract(snapshot, "$.query")
    return (
        select(TurnRow.id)
        .where(
            TurnRow.investigation_id == InvestigationRow.id,
            TurnRow.actor == actor,
            _contains_text(question, query),
            func.json_type(snapshot, "$.query") == "text",
            func.length(question) <= 8000,
            func.json_extract(snapshot, "$.schema_version") == 1,
            func.json_extract(snapshot, "$.id") == TurnRow.id,
            func.json_extract(snapshot, "$.actor") == TurnRow.actor,
            func.json_extract(snapshot, "$.host") == TurnRow.host,
            func.json_extract(snapshot, "$.investigation_id") == TurnRow.investigation_id,
            func.json_extract(snapshot, "$.state") == TurnRow.state,
            func.json_extract(snapshot, "$.revision") == TurnRow.revision,
            func.json_extract(snapshot, "$.clarification_of").is_(None),
        )
        .order_by(TurnRow.created_at.desc(), TurnRow.id.desc())
        .limit(1)
        .correlate(InvestigationRow)
        .scalar_subquery()
    )


def search_investigations(
    session: Session, actor: str, query: str, limit: int, cursor: str | None
) -> InvestigationSearchPage:
    """Scope search and continuation to owned archives without transferring saved answer payloads."""
    page_limit(limit)
    scope = f"investigations:search:{query}"
    before = decode_cursor(actor, scope, cursor)
    archive = InvestigationRow
    question = cast(func.json_extract(TurnRow.snapshot, "$.query"), String)
    statement = (
        select(archive.id, archive.host, archive.title, archive.updated_at, TurnRow.id, question)
        .outerjoin(TurnRow, TurnRow.id == _matching_turn(actor, query))
        .where(archive.actor == actor)
        .where(or_(TurnRow.id.is_not(None), _contains_text(archive.title, query), _contains_text(archive.host, query)))
    )
    if before:
        statement = statement.where(
            or_(archive.updated_at < before[0], (archive.updated_at == before[0]) & (archive.id < before[1]))
        )
    statement = statement.order_by(archive.updated_at.desc(), archive.id.desc()).limit(limit + 1)
    rows = list(session.execute(statement))
    selected = rows[:limit]
    next_cursor = encode_cursor(actor, scope, selected[-1][3], selected[-1][0]) if len(rows) > limit else None
    items = tuple(_search_hit(*row, query=query) for row in selected)
    return InvestigationSearchPage(items=items, next_cursor=next_cursor)


def _search_hit(
    identity: str, host: str, title: str, updated_at: str, turn_id: str | None, text: str | None, query: str
) -> InvestigationSearchHit:
    """Convert the nullable question projection from the outer join to a detached result."""
    return InvestigationSearchHit(
        id=identity,
        host=host,
        title=title,
        updated_at=datetime.fromisoformat(updated_at),
        match=question_match(turn_id, text, query) if turn_id is not None and text is not None else None,
    )
