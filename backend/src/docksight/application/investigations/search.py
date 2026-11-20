from bisect import bisect_left, bisect_right
from itertools import accumulate
from typing import Final

from docksight.application.investigations.contracts import InvestigationQuestionMatch
from docksight.application.investigations.errors import HistoryError

MAX_SEARCH_QUERY: Final = 120
BEFORE_MATCH: Final = 40
AFTER_MATCH: Final = 80


def search_query(value: str) -> str:
    """Bound and normalize a literal archive query without retaining the submitted spelling."""
    normalized = value.strip().casefold()
    if len(value) > MAX_SEARCH_QUERY or not normalized:
        raise HistoryError("history_query", "Enter a nonempty search query of at most 120 characters")
    return normalized


def question_match(turn_id: str, question: str, query: str) -> InvestigationQuestionMatch | None:
    """Locate the first folded match and map it back to the original excerpt for browser highlighting."""
    found = question.casefold().find(query)
    if found < 0:
        return None
    folded_offsets = list(accumulate((len(character.casefold()) for character in question), initial=0))
    start = bisect_right(folded_offsets, found) - 1
    end = bisect_left(folded_offsets, found + len(query))
    left = max(start - BEFORE_MATCH, 0)
    right = min(end + AFTER_MATCH, len(question))
    prefix = ("…" if left else "") + question[left:start]
    matched = question[start:end]
    suffix = question[end:right] + ("…" if right < len(question) else "")
    start_utf16 = len(prefix.encode("utf-16-le")) // 2
    return InvestigationQuestionMatch(
        turn_id=turn_id,
        excerpt=prefix + matched + suffix,
        start=start_utf16,
        end=start_utf16 + len(matched.encode("utf-16-le")) // 2,
    )
