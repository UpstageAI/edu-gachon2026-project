from fastapi.testclient import TestClient

from app.api.dependencies import reset_repository_bundle_cache
from app.core.config import Settings
from app.main import create_app


def _client() -> TestClient:
    reset_repository_bundle_cache()
    return TestClient(create_app(Settings(app_env="test", enable_mock_data=True)))


def test_list_topics_returns_default_catalog():
    client = _client()

    response = client.get("/api/v1/topics")

    assert response.status_code == 200
    payload = response.json()
    topic_ids = {item["topic_id"] for item in payload["topics"]}
    assert len(payload["topics"]) >= 100
    assert {"topic_btc", "topic_nasdaq", "topic_semi"}.issubset(topic_ids)


def test_add_subscription_and_list_by_user():
    client = _client()
    user_id = "api_user_add"

    response = client.post(
        f"/api/v1/subscriptions/{user_id}/topics",
        json={"topic_id": "topic_btc", "channel": "discord"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["subscription"]["user_id"] == user_id
    assert payload["subscription"]["topic_id"] == "topic_btc"

    list_response = client.get(f"/api/v1/subscriptions/{user_id}")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["user"]["user_id"] == user_id
    assert list_payload["user"]["tier"] == "free"
    assert [item["topic_id"] for item in list_payload["subscriptions"]] == ["topic_btc"]
    assert [item["topic_id"] for item in list_payload["topics"]] == ["topic_btc"]


def test_add_subscription_is_idempotent_for_same_topic_channel():
    client = _client()
    user_id = "api_user_idempotent"
    request = {"topic_id": "topic_nasdaq", "channel": "discord"}

    first = client.post(f"/api/v1/subscriptions/{user_id}/topics", json=request)
    second = client.post(f"/api/v1/subscriptions/{user_id}/topics", json=request)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["subscription"]["subscription_id"] == first.json()["subscription"][
        "subscription_id"
    ]

    list_response = client.get(f"/api/v1/subscriptions/{user_id}")
    assert [
        item["topic_id"] for item in list_response.json()["subscriptions"]
    ] == ["topic_nasdaq"]


def test_free_tier_limit_returns_409():
    client = _client()
    user_id = "api_user_limit"
    max_topics = client.get(f"/api/v1/subscriptions/{user_id}").json()["user"]["max_topics"]
    topic_ids = [item["topic_id"] for item in client.get("/api/v1/topics").json()["topics"]]

    for topic_id in topic_ids[:max_topics]:
        response = client.post(
            f"/api/v1/subscriptions/{user_id}/topics",
            json={"topic_id": topic_id, "channel": "discord"},
        )
        assert response.status_code == 201

    limit_response = client.post(
        f"/api/v1/subscriptions/{user_id}/topics",
        json={"topic_id": topic_ids[max_topics], "channel": "discord"},
    )

    assert limit_response.status_code == 409
    assert limit_response.json()["detail"]["code"] == "TOPIC_LIMIT_EXCEEDED"


def test_delete_subscription_hides_topic_from_user_list():
    client = _client()
    user_id = "api_user_delete"
    client.post(
        f"/api/v1/subscriptions/{user_id}/topics",
        json={"topic_id": "topic_usdkrw", "channel": "discord"},
    )

    delete_response = client.delete(f"/api/v1/subscriptions/{user_id}/topics/topic_usdkrw")

    assert delete_response.status_code == 200
    assert delete_response.json() == {
        "status": "deleted",
        "topic_id": "topic_usdkrw",
        "removed": True,
    }
    assert client.get(f"/api/v1/subscriptions/{user_id}").json()["subscriptions"] == []

    second_delete = client.delete(f"/api/v1/subscriptions/{user_id}/topics/topic_usdkrw")
    assert second_delete.status_code == 200
    assert second_delete.json()["removed"] is False


def test_match_topics_ranks_by_keyword_overlap():
    client = _client()

    response = client.post("/api/v1/topics/match", json={"query": "반도체", "limit": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "반도체"
    assert payload["count"] == len(payload["matches"])
    assert 1 <= len(payload["matches"]) <= 5

    topic_ids = [match["topic"]["topic_id"] for match in payload["matches"]]
    assert "topic_semi" in topic_ids
    for match in payload["matches"]:
        assert match["score"] >= 1
        assert match["matched_keywords"]

    scores = [match["score"] for match in payload["matches"]]
    assert scores == sorted(scores, reverse=True)


def test_match_topics_returns_empty_for_no_match():
    client = _client()

    response = client.post("/api/v1/topics/match", json={"query": "존재하지않는키워드zzz"})

    assert response.status_code == 200
    assert response.json() == {
        "query": "존재하지않는키워드zzz",
        "count": 0,
        "matches": [],
    }


def test_match_topics_rejects_empty_query():
    client = _client()

    response = client.post("/api/v1/topics/match", json={"query": ""})

    assert response.status_code == 422
