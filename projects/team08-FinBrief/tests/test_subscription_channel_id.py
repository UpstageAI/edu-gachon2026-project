"""Subscription.discord_channel_id 저장/조회 (memory repo)."""
from app.repositories.memory import create_memory_repositories


def test_add_stores_channel_id():
    repos = create_memory_repositories()
    topic = repos.topics.get_by_normalized_name("btc")
    user = repos.users.get_or_create("discord", "u_ch")
    sub = repos.subscriptions.add(user.user_id, topic.topic_id, "discord", "chan_999")
    assert sub.discord_channel_id == "chan_999"
    assert any(s.discord_channel_id == "chan_999" for s in repos.subscriptions.list_active())


def test_channel_id_optional_defaults_none():
    repos = create_memory_repositories()
    topic = repos.topics.get_by_normalized_name("nasdaq")
    user = repos.users.get_or_create("discord", "u_noch")
    sub = repos.subscriptions.add(user.user_id, topic.topic_id, "discord")
    assert sub.discord_channel_id is None
