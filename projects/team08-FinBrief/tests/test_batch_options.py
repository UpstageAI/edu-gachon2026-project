"""배치 트리거 옵션: 리포트/카드 발송 여부 + 특정 계정 필터."""
from app.agents import nodes
from app.repositories.memory import create_memory_repositories


def _card(topic_id):
    return {"topic_id": topic_id, "category": "MARKET", "headline": "h", "lead": "l",
            "body": "b", "source": "s", "disclaimer": "d", "image_path": None}


def _sub(topic_id, ch="9"):
    return {"user_id": "u1", "topic_id": topic_id, "channel": "discord", "discord_channel_id": ch}


def test_deliver_report_only():
    # deliver_cards=False → 카드 발송 없음, 리포트만(topic_id=None)
    out = nodes.deliver({
        "cards": [_card("nasdaq")],
        "report_url": "/tmp/r.png",
        "deliver_cards": False,
        "subscriptions": [_sub("nasdaq")],
    })
    assert out["deliveries"]
    assert all(d["topic_id"] is None for d in out["deliveries"])


def test_deliver_cards_only_no_report():
    # deliver_report=False → 리포트 없음, 카드만(topic_id 존재)
    out = nodes.deliver({
        "cards": [_card("nasdaq")],
        "report_url": "/tmp/r.png",
        "deliver_report": False,
        "subscriptions": [_sub("nasdaq")],
    })
    assert out["deliveries"]
    assert all(d["topic_id"] is not None for d in out["deliveries"])


def test_collect_topics_only_user(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    repos = create_memory_repositories()
    topic = repos.topics.get_by_normalized_name("nasdaq")
    u1 = repos.users.get_or_create("discord", "acc1")
    u2 = repos.users.get_or_create("discord", "acc2")
    repos.subscriptions.add(u1.user_id, topic.topic_id, "discord", "c1")
    repos.subscriptions.add(u2.user_id, topic.topic_id, "discord", "c2")

    out = nodes.collect_topics({"repositories": repos, "only_external_user": "acc1"})
    assert {s["user_id"] for s in out["subscriptions"]} == {u1.user_id}


def test_collect_topics_no_cards_skips_topics():
    repos = create_memory_repositories()
    topic = repos.topics.get_by_normalized_name("nasdaq")
    u1 = repos.users.get_or_create("discord", "acc1")
    repos.subscriptions.add(u1.user_id, topic.topic_id, "discord", "c1")

    out = nodes.collect_topics({"repositories": repos, "deliver_cards": False})
    assert out["unique_topics"] == []        # 카드 미발송 → 토픽 생성 스킵(비용 절감)
    assert len(out["subscriptions"]) == 1     # 구독은 유지(리포트 발송용)
