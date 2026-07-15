from datetime import date, datetime, timedelta, timezone

from app.agents import nodes, rag
from app.agents.graph import graph
from app.core.schemas import (
    IndicatorValue,
    NewsDocument,
    NewsEvidence,
    Topic,
    TopicSourceMapping,
)
from app.repositories.memory import create_memory_repositories
from app.repositories.supabase import create_supabase_repositories


def _ev(source: str, similarity: float, news_id: str) -> NewsEvidence:
    return NewsEvidence(
        news_id=news_id,
        title=f"뉴스-{news_id}",
        source=source,
        url=f"https://example.com/{news_id}",
        similarity=similarity,
        snippet="요약",
    )


def _topic_btc() -> Topic:
    return Topic(
        topic_id="topic_btc",
        name="비트코인",
        normalized_name="btc",
        type="asset",
        source_mapping=[
            TopicSourceMapping(provider="yfinance", ticker="BTC-USD", news_keywords=["비트코인", "BTC"])
        ],
    )


def _graph_topic() -> dict:
    return {"topic_id": "topic_btc", "source_key": "btc", "name": "비트코인", "category": "CRYPTO"}


# --------------------------------------------------------------------------- #
# rag post-processing helper
# --------------------------------------------------------------------------- #
def test_postprocess_filters_threshold_and_source_diversity():
    evidence = [
        _ev("a", 0.9, "1"),
        _ev("a", 0.8, "2"),
        _ev("a", 0.7, "3"),  # 3rd from source a -> dropped by diversity cap
        _ev("b", 0.1, "low"),  # below threshold -> dropped
        _ev("c", 0.5, "5"),
    ]

    out = rag.postprocess_evidence(evidence, min_similarity=0.2, max_per_source=2, k=5)

    assert [item.news_id for item in out] == ["1", "2", "5"]


def test_postprocess_caps_at_k():
    evidence = [_ev(f"s{i}", 0.9, str(i)) for i in range(10)]

    out = rag.postprocess_evidence(evidence, k=3)

    assert len(out) == 3


def test_since_for_uses_kst_same_day():
    kst = timezone(timedelta(hours=9))
    # 기본(days=0)은 해당 KST 날짜 자정 → 당일 뉴스만
    assert rag.since_for(date(2026, 7, 14)) == datetime(2026, 7, 14, tzinfo=kst)
    assert rag.since_for(date(2026, 7, 10), days=3) == datetime(2026, 7, 7, tzinfo=kst)


# --------------------------------------------------------------------------- #
# query embedding provider wiring -> match_news RPC
# --------------------------------------------------------------------------- #
class _RpcClient:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.last: tuple[str, dict] | None = None

    def rpc(self, name: str, params: dict) -> "_RpcClient":
        self.last = (name, dict(params))
        return self

    def execute(self) -> list[dict]:
        return self._rows


def test_supabase_news_match_calls_match_news_with_query_embedding():
    rows = [
        {
            "news_id": "nid",
            "title": "비트코인 급등",
            "source": "feed",
            "url": "https://example.com/1",
            "published_at": "2026-07-09T00:00:00+00:00",
            "summary": "요약",
            "similarity": 0.83,
        }
    ]
    client = _RpcClient(rows)
    bundle = create_supabase_repositories(
        client=client,
        query_embedding_provider=lambda topic: [0.0] * 4096,
    )

    out = bundle.news.match(_topic_btc(), rag.since_for(date(2026, 7, 10)), 5)

    assert len(out) == 1 and out[0].source == "feed" and out[0].similarity == 0.83
    name, params = client.last
    assert name == "match_news"
    assert len(params["query_embedding"]) == 4096
    assert "비트코인" in params["topic_tags"]
    assert params["match_count"] == 5


# --------------------------------------------------------------------------- #
# retrieve_evidence node
# --------------------------------------------------------------------------- #
class _FakeTopics:
    def __init__(self, topic: Topic) -> None:
        self._topic = topic

    def get(self, topic_id: str) -> Topic:
        return self._topic


class _FakeNews:
    def __init__(self, evidence=None, error=None) -> None:
        self._evidence = evidence or []
        self._error = error

    def match(self, topic, since, k):
        if self._error is not None:
            raise self._error
        return self._evidence


class _FakeBundle:
    def __init__(self, topic: Topic, evidence=None, error=None) -> None:
        self.topics = _FakeTopics(topic)
        self.news = _FakeNews(evidence, error)


def test_retrieve_evidence_enriches_topic_with_rag_and_indicator():
    bundle = _FakeBundle(_topic_btc(), evidence=[_ev("feed", 0.9, "1"), _ev("feed", 0.1, "low")])
    state = {
        "live_data": True,
        "repositories": bundle,
        "run_date": "2026-07-10",
        "topics_to_generate": [_graph_topic()],
        "indicators": [{"indicator_id": "topic_btc", "value": 68000, "unit": "USD", "change_pct": 1.2}],
    }

    out = nodes.retrieve_evidence(state)
    topic = out["topics_to_generate"][0]

    assert [item["news_id"] for item in topic["evidence"]] == ["1"]  # low-similarity dropped
    assert topic["indicator"]["value"] == 68000
    assert "errors" not in out


def test_retrieve_evidence_records_error_and_continues():
    bundle = _FakeBundle(_topic_btc(), error=RuntimeError("rpc down"))
    state = {
        "live_data": True,
        "repositories": bundle,
        "run_date": "2026-07-10",
        "topics_to_generate": [_graph_topic()],
        "indicators": [],
    }

    out = nodes.retrieve_evidence(state)

    assert out["topics_to_generate"][0]["evidence"] == []
    assert out["errors"][0]["code"] == "RAG_FAILED"


def test_retrieve_evidence_is_noop_when_not_live():
    assert nodes.retrieve_evidence({"live_data": False, "topics_to_generate": [_graph_topic()]}) == {}


# --------------------------------------------------------------------------- #
# collect_indicators live path (source_mapping driven, no network via monkeypatch)
# --------------------------------------------------------------------------- #
def test_collect_indicators_live_uses_source_mapping(monkeypatch):
    def fake_yf(*, ticker, indicator_id, name, **kwargs):
        return [
            IndicatorValue(
                indicator_id=indicator_id,
                name=name,
                source="yfinance",
                value_date=date(2026, 7, 10),
                current_value=68000.0,
                previous_value=67000.0,
                change_percent=1.49,
                unit="USD",
            )
        ]

    monkeypatch.setattr(nodes.yfinance_source, "fetch_yfinance_prices", fake_yf)
    monkeypatch.setattr(nodes.fred, "fetch_fred_observations", lambda **kwargs: [])

    state = {
        "live_data": True,
        "repositories": _FakeBundle(_topic_btc()),
        "run_date": "2026-07-10",
        "unique_topics": [_graph_topic()],
    }

    out = nodes.collect_indicators(state)

    assert out["indicators"][0]["indicator_id"] == "topic_btc"
    assert out["indicators"][0]["value"] == 68000.0
    assert "missing_indicators" not in out


# --------------------------------------------------------------------------- #
# graph live path end-to-end (memory repo with news -> RAG evidence on card)
# --------------------------------------------------------------------------- #
def test_graph_live_attaches_rag_evidence_to_card(monkeypatch, tmp_path):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    monkeypatch.setenv("FINBRIEF_IMAGE_STUB", "1")
    monkeypatch.setenv("FINBRIEF_OUT", str(tmp_path / "cards"))
    monkeypatch.setenv("FINBRIEF_IMG_OUT", str(tmp_path / "images"))
    monkeypatch.setattr(nodes.yfinance_source, "fetch_yfinance_prices", lambda **kwargs: [])
    monkeypatch.setattr(nodes.fred, "fetch_fred_observations", lambda **kwargs: [])

    news = [
        NewsDocument(
            news_id="n1",
            title="비트코인 ETF 자금 유입",
            source="feed",
            url="https://example.com/n1",
            published_at=datetime(2026, 7, 10, tzinfo=timezone.utc),  # run_date 당일(KST 창 내)
            summary="가상자산 ETF 자금이 유입되었습니다.",
            tags=["비트코인"],
        )
    ]
    repos = create_memory_repositories(news_documents=news)
    user = repos.users.get_or_create("discord", "u_live")
    repos.subscriptions.add(user.user_id, "topic_btc", "discord")

    final = graph.invoke(
        {
            "run_id": "live",
            "run_date": "2026-07-10",
            "status": "queued",
            "repositories": repos,
            "live_data": True,
            "ingestion": object(),
            "cards": [],
            "deliveries": [],
            "errors": [],
        }
    )

    assert final["status"] in ("completed", "partial_success")
    btc_cards = [card for card in final["cards"] if card["topic_id"] == "topic_btc"]
    assert btc_cards, "expected a card for topic_btc"
    assert btc_cards[0]["evidence"], "expected RAG evidence on the live card"
    assert any("비트코인" in item["title"] for item in btc_cards[0]["evidence"])
