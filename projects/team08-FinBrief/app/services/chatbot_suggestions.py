"""Topic suggestion helpers for conversational chatbot replies."""

from __future__ import annotations

from dataclasses import dataclass
import re

from app.core.schemas import Topic
from app.services.chatbot_persona import STARTER_TOPIC_IDS
from app.tools.news.tagging import topic_keywords


ACTION_WORDS = [
    "구독",
    "추가",
    "등록",
    "삭제",
    "취소",
    "해지",
    "빼",
    "보여줘",
    "조회",
    "추천",
    "해줘",
    "토픽",
    "내",
    "좀",
]


@dataclass(frozen=True)
class TopicSuggestion:
    topic_id: str
    name: str
    score: int
    matched_terms: tuple[str, ...]


def _tokens(query: str) -> list[str]:
    cleaned = str(query).casefold()
    for word in ACTION_WORDS:
        cleaned = cleaned.replace(word, " ")
    return [token.strip() for token in cleaned.split() if len(token.strip()) >= 2]


def _clean_action_words(query: str) -> str:
    cleaned = str(query).casefold()
    for word in ACTION_WORDS:
        cleaned = cleaned.replace(word, " ")
    return cleaned.strip()


def _canonical(value: str) -> str:
    """Normalize aliases such as S&P500, USD/KRW, fed_funds, fed funds."""

    return re.sub(r"[^0-9a-z가-힣]+", "", str(value).casefold())


def _topic_terms(topic: Topic) -> list[str]:
    terms = [topic.topic_id, topic.name, topic.normalized_name]
    for mapping in topic.source_mapping:
        if mapping.query:
            terms.append(mapping.query)
    terms.extend(topic_keywords(topic))
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        normalized = str(term).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def resolve_topic_id(query: str, catalog: list[Topic]) -> str | None:
    """Resolve high-confidence topic aliases to a single topic id.

    Exact canonical matching handles display names, normalized names, source
    queries, and news keywords. If no exact hit exists, a unique suggestion is
    safe to auto-select; multiple suggestions remain a clarification case.
    """

    query_key = _canonical(_clean_action_words(query))
    if len(query_key) >= 2:
        exact: list[Topic] = []
        for topic in catalog:
            if any(_canonical(term) == query_key for term in _topic_terms(topic)):
                exact.append(topic)
        if len(exact) == 1:
            return exact[0].topic_id

    suggestions = suggest_topics(query, catalog, limit=2)
    if len(suggestions) == 1:
        return suggestions[0].topic_id
    return None


def _term_matches_token(term_text: str, token: str) -> bool:
    if len(term_text) <= 1 or len(token) <= 1:
        return term_text == token
    return token in term_text or term_text in token


def suggest_topics(query: str, catalog: list[Topic], *, limit: int = 5) -> list[TopicSuggestion]:
    """Return a small ranked list of topic candidates for ambiguous messages."""

    tokens = _tokens(query) or [str(query).casefold()]
    suggestions: list[TopicSuggestion] = []
    for topic in catalog:
        matched: set[str] = set()
        score = 0
        for term in _topic_terms(topic):
            term_text = term.casefold()
            for token in tokens:
                if not token:
                    continue
                if _term_matches_token(term_text, token):
                    matched.add(term)
                    score += 3 if term == topic.name else 1
        if score > 0:
            suggestions.append(
                TopicSuggestion(
                    topic_id=topic.topic_id,
                    name=topic.name,
                    score=score,
                    matched_terms=tuple(sorted(matched)),
                )
            )

    suggestions.sort(key=lambda item: (-item.score, item.name))
    return suggestions[: max(limit, 0)]


def starter_topics(catalog: list[Topic], *, limit: int = 5) -> list[TopicSuggestion]:
    by_id = {topic.topic_id: topic for topic in catalog}
    items: list[TopicSuggestion] = []
    for topic_id in STARTER_TOPIC_IDS:
        topic = by_id.get(topic_id)
        if topic:
            items.append(
                TopicSuggestion(
                    topic_id=topic.topic_id,
                    name=topic.name,
                    score=1,
                    matched_terms=(),
                )
            )
    if len(items) < limit:
        for topic in catalog:
            if topic.topic_id not in {item.topic_id for item in items}:
                items.append(
                    TopicSuggestion(
                        topic_id=topic.topic_id,
                        name=topic.name,
                        score=1,
                        matched_terms=(),
                    )
                )
            if len(items) >= limit:
                break
    return items[:limit]
