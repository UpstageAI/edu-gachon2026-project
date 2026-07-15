"""Subscription and topic catalog endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.api.dependencies import get_repository_bundle
from app.core.schemas import DeliveryChannel, Subscription, Topic, UserProfile
from app.repositories.protocols import (
    RepositoryBundle,
    RepositoryNotFoundError,
    TopicLimitExceededError,
)
from app.tools.news.tagging import topic_keywords


router = APIRouter()


class SubscriptionCreateRequest(BaseModel):
    topic_id: str = Field(min_length=1)
    channel: DeliveryChannel = "discord"


class TopicMatchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=100)


def _dump_topic(topic: Topic) -> dict[str, object]:
    return topic.model_dump(mode="json")


def _dump_subscription(subscription: Subscription) -> dict[str, object]:
    return subscription.model_dump(mode="json")


def _dump_user(user: UserProfile) -> dict[str, object]:
    return user.model_dump(mode="json")


def _error_detail(error: Exception, code: str) -> dict[str, str]:
    return {"code": code, "message": str(error)}


def match_topics(topics: list[Topic], query: str, *, limit: int = 10) -> list[dict[str, object]]:
    """Rank catalog topics by how many searchable terms hit the query.

    Matching is case-insensitive and substring-based in both directions, so a
    short query token ("반도체") matches a longer keyword ("AI 반도체") and a
    long query matches a shorter keyword it contains. Searchable terms are each
    topic's ``news_keywords`` plus its display name. Single-character terms and
    tokens are ignored to avoid noise (e.g. "은" matching "은행").
    """

    query_cf = query.casefold()
    tokens = [token for token in query_cf.split() if len(token) >= 2]

    scored: list[tuple[int, str, Topic, list[str]]] = []
    for topic in topics:
        terms = list(topic_keywords(topic))
        if topic.name not in terms:
            terms.append(topic.name)

        matched: list[str] = []
        for term in terms:
            term_cf = term.casefold()
            if len(term_cf) < 2:
                continue
            if term_cf in query_cf or any(token in term_cf for token in tokens):
                matched.append(term)

        if matched:
            scored.append((len(matched), topic.name, topic, sorted(matched)))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {"topic": _dump_topic(topic), "score": score, "matched_keywords": matched}
        for score, _, topic, matched in scored[:limit]
    ]


@router.get("/topics")
def list_topics(repos: RepositoryBundle = Depends(get_repository_bundle)) -> dict[str, object]:
    topics = repos.topics.list_catalog()
    return {"topics": [_dump_topic(topic) for topic in topics]}


@router.post("/topics/match")
def match_topics_endpoint(
    request: TopicMatchRequest,
    repos: RepositoryBundle = Depends(get_repository_bundle),
) -> dict[str, object]:
    matches = match_topics(repos.topics.list_catalog(), request.query, limit=request.limit)
    return {"query": request.query, "count": len(matches), "matches": matches}


@router.get("/subscriptions/{user_id}")
def list_subscriptions(
    user_id: str,
    repos: RepositoryBundle = Depends(get_repository_bundle),
) -> dict[str, object]:
    user = repos.users.get_or_create("discord", user_id)
    subscriptions = repos.subscriptions.list_by_user(user.user_id)
    topics = [repos.topics.get(item.topic_id) for item in subscriptions]
    return {
        "user": _dump_user(user),
        "subscriptions": [_dump_subscription(item) for item in subscriptions],
        "topics": [_dump_topic(topic) for topic in topics],
    }


@router.post("/subscriptions/{user_id}/topics")
def add_subscription(
    user_id: str,
    request: SubscriptionCreateRequest,
    response: Response,
    repos: RepositoryBundle = Depends(get_repository_bundle),
) -> dict[str, object]:
    user = repos.users.get_or_create(request.channel, user_id)
    existing = next(
        (
            item
            for item in repos.subscriptions.list_by_user(user.user_id)
            if item.topic_id == request.topic_id and item.channel == request.channel
        ),
        None,
    )

    try:
        subscription = repos.subscriptions.add(user.user_id, request.topic_id, request.channel)
    except TopicLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error_detail(exc, exc.code),
        ) from exc
    except RepositoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error_detail(exc, exc.code),
        ) from exc

    response.status_code = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
    return {"subscription": _dump_subscription(subscription)}


@router.delete("/subscriptions/{user_id}/topics/{topic_id}")
def delete_subscription(
    user_id: str,
    topic_id: str,
    repos: RepositoryBundle = Depends(get_repository_bundle),
) -> dict[str, object]:
    repos.users.get_or_create("discord", user_id)
    removed = repos.subscriptions.remove(user_id, topic_id)
    return {"status": "deleted", "topic_id": topic_id, "removed": removed}
