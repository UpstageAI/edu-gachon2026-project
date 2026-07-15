"""Explain which news sources were used for today's card briefings."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from app.core.schemas import CardArtifact, NewsEvidence
from app.repositories.protocols import RepositoryBundle, RepositoryNotFoundError


DISCLAIMER = "본 브리핑은 투자 조언이 아닌 참고용 정보입니다."


def _evidence_to_source(evidence: NewsEvidence) -> dict[str, object]:
    return {
        "news_id": evidence.news_id,
        "title": evidence.title,
        "source": evidence.source,
        "url": str(evidence.url),
        "snippet": evidence.snippet,
        "similarity": evidence.similarity,
    }


def _dedupe_sources(evidence: list[NewsEvidence], max_sources: int) -> list[dict[str, object]]:
    seen: set[tuple[str, str]] = set()
    sources: list[dict[str, object]] = []
    for item in evidence:
        key = (item.source, str(item.url))
        if key in seen:
            continue
        seen.add(key)
        sources.append(_evidence_to_source(item))
        if len(sources) >= max_sources:
            break
    return sources


def _fallback_evidence(
    repos: RepositoryBundle,
    *,
    card: CardArtifact,
    max_sources: int,
) -> list[NewsEvidence]:
    try:
        topic = repos.topics.get(card.topic_id)
    except RepositoryNotFoundError:
        return []
    since = datetime.combine(card.run_date, time.min, tzinfo=timezone.utc)
    try:
        return repos.news.match(topic, since, max_sources)
    except Exception:
        return []


def _source_summary(topic_name: str, sources: list[dict[str, object]]) -> str:
    if not sources:
        return f"{topic_name} 카드뉴스에 연결된 RSS/RAG 출처가 아직 충분하지 않습니다."
    names = ", ".join(sorted({str(item.get("source")) for item in sources if item.get("source")}))
    return f"{topic_name} 카드뉴스는 {names}의 관련 기사 {len(sources)}건을 근거로 작성됐습니다."


def _reply(topic_name: str, sources: list[dict[str, object]], summary: str) -> str:
    if not sources:
        return (
            f"🧾 {topic_name} 카드뉴스 출처를 확인했어요!\n\n"
            f"{summary}\n\n"
            f"{DISCLAIMER}"
        )
    lines = [
        f"{idx}. {item['source']} - {item['title']}\n   {item['url']}"
        for idx, item in enumerate(sources, start=1)
    ]
    return (
        f"🧾 {topic_name} 카드뉴스 출처를 정리했어요!\n\n"
        f"{summary}\n\n"
        + "\n".join(lines)
        + f"\n\n{DISCLAIMER}"
    )


def build_card_source_payload(
    card: CardArtifact,
    topic_name: str,
    evidence: list[NewsEvidence],
    *,
    max_sources: int = 3,
) -> dict[str, object]:
    sources = _dedupe_sources(evidence, max_sources)
    summary = _source_summary(topic_name, sources)
    return {
        "topic_id": card.topic_id,
        "topic_name": topic_name,
        "run_date": card.run_date.isoformat(),
        "card_id": card.card_id,
        "source_summary": summary,
        "reply": _reply(topic_name, sources, summary),
        "sources": sources,
        "evidence_count": len(sources),
        "disclaimer": DISCLAIMER,
        "source": "card_evidence_rag",
    }


def get_or_build_card_source_explanation(
    repos: RepositoryBundle,
    *,
    card: CardArtifact,
    topic_name: str,
    refresh: bool = False,
    max_sources: int = 3,
) -> dict[str, object]:
    """Return a cached card source explanation or create one from evidence/RAG."""

    if not refresh:
        cached = repos.card_source_explanations.get(card.topic_id, card.run_date)
        if cached is not None:
            return {**cached, "cached": True}

    evidence = list(card.analysis.evidence)
    if not evidence:
        evidence = _fallback_evidence(repos, card=card, max_sources=max_sources)

    payload = build_card_source_payload(card, topic_name, evidence, max_sources=max_sources)
    repos.card_source_explanations.upsert(card.topic_id, card.run_date, payload)
    return {**payload, "cached": False}


def _topic_name(repos: RepositoryBundle, topic_id: str) -> str:
    try:
        return repos.topics.get(topic_id).name
    except RepositoryNotFoundError:
        return topic_id


def get_user_card_source_explanations(
    repos: RepositoryBundle,
    *,
    user_id: str,
    run_date: date,
    topic_id: str | None = None,
    refresh: bool = False,
    max_sources: int = 3,
) -> dict[str, Any]:
    """Build source explanations for a user's subscribed cards."""

    user = repos.users.get_or_create("discord", user_id)
    cards: list[CardArtifact] = []
    for subscription in repos.subscriptions.list_by_user(user.user_id):
        if topic_id and subscription.topic_id != topic_id:
            continue
        card = repos.cards.get(subscription.topic_id, run_date)
        if card is not None:
            cards.append(card)

    explanations = [
        get_or_build_card_source_explanation(
            repos,
            card=card,
            topic_name=_topic_name(repos, card.topic_id),
            refresh=refresh,
            max_sources=max_sources,
        )
        for card in cards
    ]
    return {
        "user_id": user_id,
        "run_date": run_date.isoformat(),
        "cards": explanations,
        "disclaimer": DISCLAIMER,
    }
