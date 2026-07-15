import pytest
from app.services.subscription_service import SubscriptionService, TopicNotAllowed, MaxTopicsExceeded
from app.repositories.memory import create_memory_repositories


def _svc():
    return SubscriptionService(create_memory_repositories())


def _catalog_ids(svc):
    return [t.topic_id for t in svc.catalog()]


def test_whitelist():
    with pytest.raises(TopicNotAllowed):
        _svc().add("discord", "u1", "no_such_topic")


def test_persists_channel_id():
    svc = _svc()
    tid = _catalog_ids(svc)[0]
    subs = svc.add("discord", "u1", tid, channel_id="99999")
    assert any(s.topic_id == tid and s.discord_channel_id == "99999" for s in subs)


def test_max_topics():
    svc = _svc()
    tids = _catalog_ids(svc)[:6]
    for tid in tids[:5]:
        svc.add("discord", "u1", tid)
    with pytest.raises(MaxTopicsExceeded):
        svc.add("discord", "u1", tids[5])


def test_crud():
    svc = _svc()
    tid = _catalog_ids(svc)[0]
    subs = svc.add("discord", "u1", tid)
    assert any(s.topic_id == tid for s in subs)
    # idempotent — 중복 추가해도 1개
    again = svc.add("discord", "u1", tid)
    assert len([s for s in again if s.topic_id == tid]) == 1
    after = svc.remove("discord", "u1", tid)
    assert all(s.topic_id != tid for s in after)
