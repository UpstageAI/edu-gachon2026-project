"""Repository contracts shared by API routes and agent nodes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from app.core.schemas import (
    BatchRunResult,
    CardArtifact,
    EvaluationResult,
    NewsEvidence,
    Subscription,
    Topic,
    UserProfile,
)


class RepositoryError(RuntimeError):
    """Base class for repository-layer errors with stable API codes."""

    code = "REPOSITORY_ERROR"


class RepositoryNotFoundError(RepositoryError):
    """Raised when a requested row-like domain object does not exist."""

    code = "NOT_FOUND"


class TopicLimitExceededError(RepositoryError):
    """Raised when a free-tier user exceeds the allowed active topic count."""

    code = "TOPIC_LIMIT_EXCEEDED"


class TopicRepository(Protocol):
    def list_catalog(self) -> list[Topic]: ...

    def get(self, topic_id: str) -> Topic: ...

    def get_by_normalized_name(self, normalized_name: str) -> Topic | None: ...


class SubscriptionRepository(Protocol):
    def list_active(self) -> list[Subscription]: ...

    def list_by_user(self, user_id: str) -> list[Subscription]: ...

    def add(self, user_id: str, topic_id: str, channel: str,
            channel_id: str | None = None) -> Subscription: ...

    def remove(self, user_id: str, topic_id: str) -> bool: ...


class UserRepository(Protocol):
    def get_or_create(self, channel: str, external_user_id: str) -> UserProfile: ...


class CardRepository(Protocol):
    def get(self, topic_id: str, run_date: date) -> CardArtifact | None: ...

    def upsert(self, card: CardArtifact) -> None: ...


class NewsRepository(Protocol):
    def match(self, topic: Topic, since: datetime, k: int) -> list[NewsEvidence]: ...


class EvaluationRepository(Protocol):
    def insert_many(self, results: list[EvaluationResult]) -> None: ...

    def list_by_run(self, run_id: str) -> list[EvaluationResult]: ...


class ReportRunRepository(Protocol):
    def upsert(self, result: BatchRunResult) -> None: ...

    def get_by_run_id(self, run_id: str) -> BatchRunResult | None: ...

    def get_by_date(self, run_date: date) -> BatchRunResult | None: ...

    def get_latest(self) -> BatchRunResult | None: ...


class ReportExplanationRepository(Protocol):
    def get_by_run_id(self, run_id: str) -> dict[str, object] | None: ...

    def upsert(self, run_id: str, payload: dict[str, object]) -> None: ...


class CardSourceExplanationRepository(Protocol):
    def get(self, topic_id: str, run_date: date) -> dict[str, object] | None: ...

    def upsert(self, topic_id: str, run_date: date, payload: dict[str, object]) -> None: ...


@dataclass(slots=True)
class RepositoryBundle:
    users: UserRepository
    topics: TopicRepository
    subscriptions: SubscriptionRepository
    cards: CardRepository
    news: NewsRepository
    evals: EvaluationRepository
    reports: ReportRunRepository
    report_explanations: ReportExplanationRepository
    card_source_explanations: CardSourceExplanationRepository
