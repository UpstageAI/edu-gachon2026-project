from app.agents.graph import graph
from app.repositories.memory import create_memory_repositories


def _prepare_offline_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    monkeypatch.setenv("FINBRIEF_IMAGE_STUB", "1")
    monkeypatch.setenv("FINBRIEF_OUT", str(tmp_path / "cards"))
    monkeypatch.setenv("FINBRIEF_IMG_OUT", str(tmp_path / "images"))
    monkeypatch.setenv("DELIVERY_DRY_RUN", "true")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")   # 봇 발송 경로 활성


def test_graph_collects_unique_topics_from_repository_subscriptions(monkeypatch, tmp_path):
    _prepare_offline_env(monkeypatch, tmp_path)
    # 봇 토큰+채널ID 설정 시 발송 경로를 타고 DRY_RUN(기본)이라 "dry_run" 상태가 됨.
    repos = create_memory_repositories()
    topic = repos.topics.get_by_normalized_name("btc")
    first_user = repos.users.get_or_create("discord", "graph_user_001")
    second_user = repos.users.get_or_create("discord", "graph_user_002")
    repos.subscriptions.add(first_user.user_id, topic.topic_id, "discord", "chan-1")
    repos.subscriptions.add(second_user.user_id, topic.topic_id, "discord", "chan-2")

    final = graph.invoke(
        {
            "run_id": "graph_unique",
            "run_date": "2026-07-10",
            "status": "queued",
            "repositories": repos,
            "cards": [],
            "deliveries": [],
            "errors": [],
        }
    )

    assert final["status"] == "completed"
    assert [item["topic_id"] for item in final["cards"]] == [topic.topic_id]
    assert {item["user_id"] for item in final["deliveries"]} == {
        first_user.user_id,
        second_user.user_id,
    }
    # DELIVERY_DRY_RUN 기본(true) → 오프라인에선 실제 전송 없이 "dry_run" 상태.
    assert all(item["status"] == "dry_run" for item in final["deliveries"])


def test_graph_reuses_cached_card_on_second_run(monkeypatch, tmp_path):
    _prepare_offline_env(monkeypatch, tmp_path)
    repos = create_memory_repositories()
    topic = repos.topics.get_by_normalized_name("nasdaq")
    user = repos.users.get_or_create("discord", "graph_user_cache")
    repos.subscriptions.add(user.user_id, topic.topic_id, "discord")
    state = {
        "run_id": "graph_cache",
        "run_date": "2026-07-10",
        "status": "queued",
        "repositories": repos,
        "cards": [],
        "deliveries": [],
        "errors": [],
    }

    first = graph.invoke(state)
    second = graph.invoke({**state, "run_id": "graph_cache_second"})

    assert first["generated_count"] == 1
    assert first["reused_count"] == 0
    assert second["generated_count"] == 0
    assert second["reused_count"] == 1
    assert second["cards"][0]["topic_id"] == topic.topic_id
    assert second["cards"][0]["cached"] is True


def test_graph_handles_no_repository_subscriptions(monkeypatch, tmp_path):
    _prepare_offline_env(monkeypatch, tmp_path)
    repos = create_memory_repositories()

    final = graph.invoke(
        {
            "run_id": "graph_empty",
            "run_date": "2026-07-10",
            "status": "queued",
            "repositories": repos,
            "cards": [],
            "deliveries": [],
            "errors": [],
        }
    )

    assert final["status"] == "completed"
    assert final["cards"] == []
    assert final["deliveries"] == []
    assert final["generated_count"] == 0
    assert final["reused_count"] == 0
