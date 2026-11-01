"""Bounded EN/RU regression checks for authored single-target causal explanations.

This transparent heuristic is neither a general language validator nor a factuality judge. The fixture profile is
supplied by the test, never inferred from model prose. Clause-local polarity covers the authored corpus; new idioms,
cross-sentence coreference, mixed-resource summaries, and arbitrary historical narratives require manual review.
The unhealthy fixture's observed HTTP 503 probe response is a known symptom, not an established root cause.
Its bounded unsupported-cause families are SQL/database or dependency failures and asserted restart cures.
Follow-ups additionally check authored categorical independence claims; differing failures do not establish no link.
"""

import re
from collections.abc import Iterator
from typing import Final, Literal

from docksight.application.views.schemas import ContainerStatusCard, DiagnosisResponse, LogAnomalyCard

type CausalProfile = Literal["clean_shutdown", "unknown_exit", "oom", "running_unhealthy", "running_history"]
type Stance = Literal["affirmed", "denied", "possible", "context"]

_CLAUSES: Final = re.compile(
    r"[.!;\n]+|(?<!not )\byet\b|\b(?:but|however|although|но|однако|зато)\b|"
    r"(?:,\s*(?:\u0430\s+)?|\b(?:and|и)\s+)(?=(?:the |worker\b|target\b|docker\b|контейнер\b|процесс\b|он\b))",
    re.I,
)
_CRASH: Final = re.compile(
    r"\bcrash(?:ed|es|ing)?\b|\bcrash[- ]loop\w*|\babnormal (?:exit|termination|shutdown)\b|"
    r"аварийн\w*\s+заверш\w*|\b(?:падает|падение|упал|упала)\b",
    re.I,
)
_STOP: Final = re.compile(
    r"\b(?:container|process|worker|target|server|service|it)\b.{0,45}?"
    r"\b(?:stopped(?!\s+\w+ing\b)|exited|dead|terminated|shut down)\b|"
    r"\b(?:stopped|dead)\s+(?:container|worker|target|process)\b|"
    r"(?:контейнер|процесс|worker|target|сервер|сервис).{0,40}?"
    r"(?:остановлен\w*|завершился|завершен\w*|не\s+работает)",
    re.I,
)
_RUNNING: Final = re.compile(
    r"\b(?:container|process|worker|target|server|it)\b.{0,35}?\b(?:is|remains|still)\s+(?:currently\s+)?running\b|"
    r"(?:контейнер|процесс|worker|target|сервер)\s+(?:сейчас\s+|все еще\s+)?"
    r"(?:работает|запущен|продолжает\s+работать)\b",
    re.I,
)
_HEALTHY: Final = re.compile(
    r"\b(?:service|worker|target|container|server)\b.{0,30}?\b(?:is|remains)\s+"
    r"(?:currently\s+)?(?:running\s+and\s+)?(?:fully\s+)?healthy\b|"
    r"(?:сервис|контейнер|процесс|target).{0,25}?\b(?:исправен|здоров)\b",
    re.I,
)
_OOM: Final = re.compile(
    r"\boomkilled\s*=\s*(?:true|false)\b|\boom(?:[- ]killed|[- ]kill|[- ]заверш\w*)?\b|\bout[- ]of[- ]memory\b|"
    r"\bmemory (?:pressure|limit|exhaustion)\b|(?:нехватк\w*|недостат\w*|исчерпан\w*|переполн\w*)\s+памят\w*",
    re.I,
)
_OOM_EVENT: Final = re.compile(
    r"\boomkilled\s*=\s*true\b|\boom[- ]kill(?:ed|er)?\b|\boom[- ]заверш\w*|"
    r"\b(?:killed|terminated|exited|termination)\b.{0,50}?"
    r"\b(?:because of|due to|from)\s+(?:memory exhaustion|lack of memory|out[- ]of[- ]memory)\b|"
    r"\bout[- ]of[- ]memory\b.{0,25}?\b(?:kill|killed|termination)\b|"
    r"(?:заверш\w*|убит\w*|останов\w*).{0,45}?(?:из-за|от|по причине)\s+"
    r"(?:нехватк\w*|недостат\w*|исчерпан\w*|переполн\w*)\s+памят\w*",
    re.I,
)
_SIGNAL: Final = re.compile(r"\bsigkill\b|\bsignal\s*9\b|сигнал\w*\s*9\b", re.I)
_SQL: Final = re.compile(
    r"\b(?:sql|database errors?|foreign key|unique constraint|integrity|bad data)\b|"
    r"внешн\w*\s+ключ\w*|уникальн\w*|целостност\w*|некорректн\w*\s+данн\w*",
    re.I,
)
_DEPENDENCY_FAILURE: Final = re.compile(
    r"\b(?:database|dependenc(?:y|ies))\b.{0,40}?\b(?:unavailable|unreachable|down|offline|misconfigured)\b|"
    r"\b(?:unavailable|unreachable|failed|missing)\s+(?:database|dependency)\b|"
    r"(?:баз[аы]\s+данных|зависимост\w*|бд)\b.{0,35}?(?:недоступ\w*|отказ\w*|не\s+работ\w*)|"
    r"(?:недоступ\w*|отказавш\w*)\s+(?:зависимост\w*|баз[аы]\s+данных)",
    re.I,
)
_RESTART_CURE: Final = re.compile(
    r"\brestart\w*\b.{0,60}?\b(?:fix|resolv|restor|cur)\w*\b|"
    r"перезапус[кт]\w*.{0,65}?(?:исправ\w*|устран\w*|реш\w*|восстанов\w*)",
    re.I,
)
_EXIT: Final = re.compile(r"\b(?:stop\w*|exit\w*|shutdown|crash\w*)\b|останов\w*|заверш\w*", re.I)
_CAUSAL: Final = re.compile(
    r"\b(?:because|caused?|causing|due to|result(?:ed|ing)? (?:in|from))\b|"
    r"из-за|вызва[нл]\w*|привел\w*|привёл\w*|причин\w*",
    re.I,
)
_INITIATOR: Final = re.compile(
    r"\b(?:operator|administrator|user|docker|orchestrator)\b.{0,35}?\b(?:stopped|requested|initiated|sent)\b|"
    r"\b(?:stopped|requested|initiated)\b.{0,30}?\b(?:operator|administrator|user|orchestrator)\b|"
    r"(?:оператор|пользователь|администратор|оркестратор).{0,30}?(?:остановил|инициировал|отправил)",
    re.I,
)
_POSSIBLE: Final = re.compile(
    r"\b(?:may|might|could|possibly|possible|perhaps|whether|hypothesis|suspect\w*)\b|"
    r"\btypically\s+indicates\b|\b(?:often|usually)\s+(?:sigkill|signal)\b|\bfor example\b|"
    r"возможно|может\b|мог\w*\b|вероятн\w*|гипотез\w*|провер\w*.{0,20}\bли\b",
    re.I,
)
_POSSIBLE_AFTER: Final = re.compile(
    r"\s+(?:is|was|remains)\s+(?:only\s+|a\s+)?(?:possible|hypothesis|suspected)\b", re.I
)
_DENIED_AFTER: Final = re.compile(
    r"\s+(?:(?:is|was|has been)\s+)?(?:not\b|unconfirmed\b|cannot\b|can\s+not\b|не\b)", re.I
)
_CONFIRMED_BEFORE: Final = re.compile(r"\b(?:confirmed|observed)\s+$", re.I)
_CAUSE_SCOPE: Final = re.compile(r"\b(?:because|due to|except|кроме|потому что|поскольку)\b|из-за", re.I)
_NEGATIVE_PREDICATE: Final = re.compile(r"\b\u043d\u0435\s+работает\b", re.I)
_DENIED: Final = re.compile(
    r"\b(?:not|no|never|without|cannot|can't|doesn't|didn't|hasn't|isn't|rather than|instead of)\b|"
    r"\b\u043d\u0435\b|нельзя|нет\b|отсутств\w*|неизвест(?:но|ен|на|ны)\b|неподтвержд\w*",
    re.I,
)
_UNRESOLVED: Final = re.compile(
    r"\b(?:unknown|unclear|unestablished|unresolved|"
    r"not (?:yet )?(?:known|established|determined|confirmed|establish|observed|reported))\b|"
    r"неизвест\w*|неяс\w*|не\s+(?:установлен\w*|определен\w*|подтвержден\w*|позволя\w*\s+установить)",
    re.I,
)
_QUESTION: Final = re.compile(
    r"\s*(?:what|who|why|which|how|could|whether|почему|кто|что|какой|какая|как)\b[^?]*\??\s*", re.I
)
_HISTORY: Final = re.compile(r"\b(?:historical|previous|previously|earlier|past|ранее|раньше)\b", re.I)
_PAST_TIME: Final = re.compile(r"\s+(?:yesterday|last (?:week|month|year)|вчера|на прошлой неделе)\b", re.I)
_CURRENT: Final = re.compile(r"\b(?:now|currently|actively|сейчас|теперь)\b", re.I)
_OTHER: Final = re.compile(r"\b(?:another|other)\s+(?:container|process|service)\b|друг\w*\s+контейнер\w*", re.I)
_RELATION_DENIAL: Final = re.compile(r"\bnot\s+(?:causally\s+)?related\b|\b\u043d\u0435\s+связан\w*", re.I)
_UNRELATED: Final = re.compile(r"\bunrelated\b", re.I)
_CAUSE_TOPICS: Final = {
    "clean_shutdown": re.compile(
        r"initiator|shutdown|stop|terminat|who|signal|останов|заверш|инициатор|кто|сигнал", re.I
    ),
    "unknown_exit": re.compile(r"exit|stop|reason|cause|signal|причин|заверш|выход|сигнал", re.I),
    "running_unhealthy": re.compile(r"health|reason|cause|check|здоров|провер|причин|\b503\b", re.I),
}


def _narrative(answer: DiagnosisResponse) -> Iterator[tuple[str, str]]:
    """Visit every model-authored displayed field, excluding server facts and raw observations."""
    yield "summary", answer.summary
    if answer.cause:
        yield "cause.immediate", answer.cause.immediate
        if answer.cause.underlying:
            yield "cause.underlying", answer.cause.underlying
        for text in answer.cause.unknowns:
            yield "cause.unknowns", text
    for card in answer.widgets:
        if isinstance(card, ContainerStatusCard) and card.recommendation and card.recommendation.reason:
            yield "recommendation", card.recommendation.reason


def _without_observations(text: str, answer: DiagnosisResponse) -> str:
    """Remove exact quoted collected log lines and references, preserving arbitrary quoted model claims."""
    messages = (
        entry.message for card in answer.widgets if isinstance(card, LogAnomalyCard) for entry in card.logs.entries
    )
    for message in sorted(messages, key=len, reverse=True):
        for left, right in (("`", "`"), ('"', '"'), ("'", "'"), ("«", "»"), ("“", "”")):
            text = text.replace(f"{left}{message}{right}", " ")
    for evidence in answer.evidence:
        text = re.sub(rf"(?<!\w){re.escape(evidence.id)}(?!\w)", " ", text)
    normalized = _without_identifiers(text, answer).casefold().replace("\u0451", "\u0435")
    return re.sub(r"\be\.g\.", "for example", normalized)


def _without_identifiers(text: str, answer: DiagnosisResponse) -> str:
    """Normalize exact observed names and opaque IDs so their length cannot hide a nearby assertion."""
    for card in answer.widgets:
        if isinstance(card, ContainerStatusCard):
            text = re.sub(rf"(?<!\w){re.escape(card.snapshot.id)}(?!\w)", "", text, flags=re.I)
            text = re.sub(rf"(?<![\w-]){re.escape(card.snapshot.name)}(?![\w-])", "target", text, flags=re.I)
    return text


def _historical_context(prefix: str, claim: str, suffix: str) -> bool:
    """Recognize explicit past context without transferring it to a present inferred state."""
    if _CURRENT.search(prefix + claim) or _CAUSAL.search(prefix):
        return False
    return bool(_HISTORY.search(prefix + claim) or _PAST_TIME.match(suffix))


def _stance(clause: str, match: re.Match[str]) -> Stance:
    """Resolve local negation and explicit hypotheses without hiding assertions in a later clause."""
    prefix = clause[: match.start()]
    claim = match.group()
    suffix = clause[match.end() : match.end() + 55]
    if _historical_context(prefix, claim, suffix) or _OTHER.search(prefix + claim):
        return "context"
    if _POSSIBLE.search(prefix + claim) or _POSSIBLE_AFTER.match(suffix):
        return "possible"
    if "=false" in claim.replace(" ", ""):
        return "denied"
    if _NEGATIVE_PREDICATE.search(claim):
        return "affirmed"
    if _CONFIRMED_BEFORE.search(prefix) and not _DENIED.search(prefix[-25:]):
        return "affirmed"
    if _DENIED.search(_CAUSE_SCOPE.split(prefix)[-1] + claim) or _DENIED_AFTER.match(suffix):
        return "denied"
    return "affirmed"


def _stances(clause: str, pattern: re.Pattern[str]) -> set[Stance]:
    """Classify each recognized claim instead of treating a topic word as a contradiction."""
    return {_stance(clause, match) for match in pattern.finditer(clause)}


def _assert_absent(clause: str, pattern: re.Pattern[str], field: str, reason: str) -> None:
    """Reject an asserted incompatible fact while allowing denials and investigative hypotheses."""
    assert "affirmed" not in _stances(clause, pattern), f"{field}: {reason}: {clause}"


def _check_shutdown(clause: str, field: str) -> None:
    """Keep a clean exit separate from active failure, historical SQL errors, and unknown initiators."""
    _assert_absent(clause, _RUNNING, field, "the process is stopped")
    _assert_absent(clause, _CRASH, field, "exit 0 with orderly shutdown is not a crash")
    _assert_absent(clause, _OOM, field, "the clean exit is not an OOM kill")
    _assert_absent(clause, _INITIATOR, field, "the stop initiator is not established")
    if _SQL.search(clause) and _EXIT.search(clause) and _CAUSAL.search(clause):
        _assert_absent(clause, _CAUSAL, field, "historical SQL errors do not establish the stop cause")


def _check_running(clause: str, field: str) -> None:
    """Do not equate failed health or SQL history with process termination or application health."""
    _assert_absent(clause, _STOP, field, "the process remains running")
    _assert_absent(clause, _CRASH, field, "the process remains running")
    _assert_absent(clause, _HEALTHY, field, "running does not establish service health")


def _check_health_uncertainty(clause: str, field: str) -> None:
    """Preserve unknown health causes without inventing database failures or established restart cures."""
    assert not (_HEALTHY.search(clause) and _UNRESOLVED.search(clause)), (
        f"{field}: the unhealthy result is observed, not unknown: {clause}"
    )
    _assert_absent(clause, _DEPENDENCY_FAILURE, field, "a database or dependency failure is not established")
    _assert_absent(clause, _RESTART_CURE, field, "a restart cure is not established")
    if _SQL.search(clause) and _CAUSAL.search(clause) and _CAUSE_TOPICS["running_unhealthy"].search(clause):
        _assert_absent(clause, _CAUSAL, field, "SQL errors do not establish the health failure's root cause")


def _check_oom(clause: str, field: str, confirmed: bool) -> bool:
    """Distinguish an observed Docker OOM kill from unsupported interpretations of exit 137."""
    _assert_absent(clause, _RUNNING, field, "the process is stopped")
    stances = _stances(clause, _OOM)
    if confirmed:
        assert "denied" not in stances, f"{field}: Docker confirms OOM: {clause}"
    else:
        assert "affirmed" not in stances, f"{field}: OOM is not established: {clause}"
        _assert_absent(clause, _SIGNAL, field, "exit 137 alone does not establish SIGKILL")
    return "affirmed" in _stances(clause, _OOM_EVENT)


def _preserves_unknown(field: str, clause: str, topic: re.Pattern[str]) -> bool:
    """Recognize a relevant unresolved statement or a real question in the typed unknowns field."""
    if not topic.search(clause):
        return False
    if _UNRESOLVED.search(clause):
        return True
    return field == "cause.unknowns" and bool(_QUESTION.fullmatch(clause)) and not _SQL.search(clause)


def _check_unknown_cause(answer: DiagnosisResponse, profile: CausalProfile, fields: list[tuple[str, str]]) -> None:
    """Require unresolved causes to remain explicit without accepting an invented deeper cause."""
    if profile not in {"clean_shutdown", "unknown_exit", "running_unhealthy"}:
        return
    assert answer.uncertain or (answer.cause and answer.cause.unknowns), "The fixture cause is unresolved"
    topic = _CAUSE_TOPICS[profile]
    assert any(_preserves_unknown(field, clause, topic) for field, text in fields for clause in _CLAUSES.split(text)), (
        "The narrative must explicitly preserve the unresolved fixture cause"
    )
    if answer.cause:
        assert answer.cause.underlying is None, "The fixture does not establish a deeper cause"


def _check_clause(clause: str, field: str, profile: CausalProfile) -> bool:
    """Apply one fixture's independent lifecycle and cause constraints to one assertion scope."""
    if profile == "clean_shutdown":
        _check_shutdown(clause, field)
    elif profile.startswith("running_"):
        _check_running(clause, field)
        if profile == "running_unhealthy":
            _check_health_uncertainty(clause, field)
    elif profile in {"oom", "unknown_exit"}:
        return _check_oom(clause, field, profile == "oom")
    return False


def check_causality(answer: DiagnosisResponse, profile: CausalProfile, *, relationship_unknown: bool = False) -> None:
    """Reject known fixture contradictions in every narrative field of a single-target diagnosis.

    Profiles cover one container or a one-member follow-up group, never a mixed host or group summary. Unknowns and
    action reasons remain model assertions; exact quoted log observations are excluded. Checks deliberately avoid
    production helpers, model calls, exact response wording, and treating every error keyword as a causal claim.
    """
    fields = [(field, _without_observations(text, answer)) for field, text in _narrative(answer)]
    _check_unknown_cause(answer, profile, fields)
    recognized_oom = False
    for field, text in fields:
        for clause in _CLAUSES.split(text):
            recognized_oom |= _check_clause(clause, field, profile)
            if relationship_unknown:
                _assert_absent(
                    _RELATION_DENIAL.sub("unrelated", clause),
                    _UNRELATED,
                    field,
                    "different project failures do not establish that they are unrelated",
                )
    if profile == "oom":
        assert recognized_oom, "A confirmed Docker OOM kill must be recognized in the model narrative"
