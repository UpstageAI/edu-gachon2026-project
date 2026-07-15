"""SubscriptionService — 구독/토픽 CRUD + MVP 화이트리스트 + max_topics.
   RepositoryBundle 프로토콜(모델 기반) 사용 → 봇과 그래프가 동일 repo 계약 공유.
   비즈니스 로직은 여기 집중(레이어 규율). LLM/봇 아님."""
from __future__ import annotations

from app.repositories.protocols import RepositoryBundle


class TopicNotAllowed(Exception):
    pass


class MaxTopicsExceeded(Exception):
    pass


class SubscriptionService:
    def __init__(self, repos: RepositoryBundle):
        self.repos = repos

    def catalog(self):
        return self.repos.topics.list_catalog()

    def _allowed(self) -> set[str]:
        return {t.topic_id for t in self.repos.topics.list_catalog()}

    def add(self, channel: str, ext_user_id: str, topic_id: str, channel_id: str | None = None):
        if topic_id not in self._allowed():
            raise TopicNotAllowed(topic_id)
        user = self.repos.users.get_or_create(channel, ext_user_id)
        current = self.repos.subscriptions.list_by_user(user.user_id)
        if any(s.topic_id == topic_id for s in current):
            return current
        if len(current) >= user.max_topics:
            raise MaxTopicsExceeded(user.max_topics)
        self.repos.subscriptions.add(user.user_id, topic_id, channel, channel_id)
        return self.repos.subscriptions.list_by_user(user.user_id)

    def remove(self, channel: str, ext_user_id: str, topic_id: str):
        user = self.repos.users.get_or_create(channel, ext_user_id)
        self.repos.subscriptions.remove(user.user_id, topic_id)
        return self.repos.subscriptions.list_by_user(user.user_id)

    def list(self, channel: str, ext_user_id: str):
        user = self.repos.users.get_or_create(channel, ext_user_id)
        return self.repos.subscriptions.list_by_user(user.user_id)

    def tier(self, channel: str, ext_user_id: str):
        user = self.repos.users.get_or_create(channel, ext_user_id)
        used = len(self.repos.subscriptions.list_by_user(user.user_id))
        return {"tier": user.tier, "max_topics": user.max_topics, "used": used}
