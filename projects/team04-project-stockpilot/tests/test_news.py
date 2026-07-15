from datetime import datetime, timedelta, timezone
import asyncio

import httpx
import pytest

from app.repositories import news as news_repo
from app.repositories.news import (
    get_company_news,
    get_stock_issue_news,
    rule_filter,
    search_news,
)


def _news_item(
    *,
    title: str,
    description: str,
    url: str,
    days_ago: int = 0,
) -> dict:
    published = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "title": title,
        "description": description,
        "originallink": url,
        "link": url,
        "pubDate": published.strftime("%a, %d %b %Y %H:%M:%S %z"),
    }


@pytest.mark.asyncio
async def test_search_news_normalizes_html_and_deduplicates(monkeypatch):
    monkeypatch.setattr("app.repositories.news.settings.naver_client_id", "client-id")
    monkeypatch.setattr(
        "app.repositories.news.settings.naver_client_secret",
        "client-secret",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Naver-Client-Id"] == "client-id"
        assert request.url.params["sort"] == "date"
        item = _news_item(
            title="<b>삼성전자</b> 실적 발표",
            description="영업이익이 증가했다.",
            url="https://example.com/news/1?tracking=abc",
        )
        duplicate = {**item, "link": "https://example.com/duplicate"}
        return httpx.Response(200, json={"items": [item, duplicate]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await search_news("삼성전자", client=client)

    assert len(items) == 1
    assert items[0]["title"] == "삼성전자 실적 발표"
    assert items[0]["published_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_search_news_reuses_short_cache(monkeypatch):
    monkeypatch.setattr("app.repositories.news.settings.naver_client_id", "client-id")
    monkeypatch.setattr(
        "app.repositories.news.settings.naver_client_secret",
        "client-secret",
    )
    with news_repo._NEWS_CACHE_LOCK:
        news_repo._NEWS_CACHE.clear()

    calls = 0

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                json={
                    "items": [
                        _news_item(
                            title=f"Samsung earnings {calls}",
                            description="Profit improved",
                            url="https://example.com/cache",
                        )
                    ]
                },
            )

    monkeypatch.setattr(news_repo.httpx, "AsyncClient", FakeAsyncClient)

    first = await search_news("Samsung")
    second = await search_news("Samsung")

    assert calls == 1
    assert second == first

    second[0]["title"] = "mutated"
    third = await search_news("Samsung")
    assert third[0]["title"] == first[0]["title"]

    with news_repo._NEWS_CACHE_LOCK:
        news_repo._NEWS_CACHE.clear()


def test_rule_filter_scores_company_and_financial_keywords():
    items = [
        {
            "title": "삼성전자 2분기 영업이익 증가",
            "description": "반도체 매출이 늘었다.",
            "source_domain": "yna.co.kr",
            "published_timestamp": 100,
        },
        {
            "title": "오늘의 날씨",
            "description": "삼성전자가 언급됐지만 직접 관련 없는 기사다.",
            "source_domain": "example.com",
            "published_timestamp": 200,
        },
        {
            "title": "다른 회사 영업이익 급락",
            "description": "해당 기업과 무관한 금융 기사다.",
            "source_domain": "example.com",
            "published_timestamp": 300,
        },
        {
            "title": "코스피 반도체주 약세",
            "description": "삼성전자와 SK하이닉스가 동반 하락했다.",
            "source_domain": "example.com",
            "published_timestamp": 400,
        },
    ]

    filtered = rule_filter(items, company="삼성전자")

    assert len(filtered) == 2
    assert filtered[0]["relevance_score"] >= 8
    assert filtered[0]["direct_company_match"] is True
    assert "영업이익" in filtered[0]["matched_keywords"]
    assert filtered[1]["direct_company_match"] is False
    assert filtered[1]["market_context_match"] is True


@pytest.mark.asyncio
async def test_get_company_news_filters_old_items(monkeypatch):
    monkeypatch.setattr("app.repositories.news.settings.naver_client_id", "client-id")
    monkeypatch.setattr(
        "app.repositories.news.settings.naver_client_secret",
        "client-secret",
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    _news_item(
                        title="삼성전자 신규 공급 계약",
                        description="대형 수주를 공시했다.",
                        url="https://example.com/recent",
                    ),
                    _news_item(
                        title="삼성전자 과거 뉴스",
                        description="오래된 기사다.",
                        url="https://example.com/old",
                        days_ago=30,
                    ),
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await get_company_news(
            "삼성전자",
            days=7,
            client=client,
        )

    assert len(items) == 1
    assert items[0]["original_link"].endswith("/recent")


@pytest.mark.asyncio
async def test_get_stock_issue_news_prioritizes_downward_issue(monkeypatch):
    monkeypatch.setattr("app.repositories.news.settings.naver_client_id", "client-id")
    monkeypatch.setattr(
        "app.repositories.news.settings.naver_client_secret",
        "client-secret",
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    _news_item(
                        title="삼성전자 실적 우려에 주가 급락",
                        description="영업이익 감소 우려로 약세를 보였다.",
                        url="https://example.com/down",
                    ),
                    _news_item(
                        title="삼성전자 신제품 공개",
                        description="새로운 제품을 선보였다.",
                        url="https://example.com/product",
                    ),
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await get_stock_issue_news(
            "삼성전자",
            direction="down",
            client=client,
        )

    assert items[0]["original_link"].endswith("/down")
    assert "급락" in items[0]["direction_keywords"]
    assert items[0]["issue_score"] > items[1]["issue_score"]
    assert items[0]["has_direction_evidence"] is True


@pytest.mark.asyncio
async def test_get_stock_issue_news_marks_weak_direction_evidence_as_fallback(monkeypatch):
    monkeypatch.setattr("app.repositories.news.settings.naver_client_id", "client-id")
    monkeypatch.setattr(
        "app.repositories.news.settings.naver_client_secret",
        "client-secret",
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    _news_item(
                        title="현대로템 K-방산 수출 기대 속 주목",
                        description="현대로템 방산 사업과 수출 기대감이 커지고 있다.",
                        url="https://example.com/neutral",
                    ),
                    _news_item(
                        title="현대로템 신규 전장 기술 공개",
                        description="유무인 체계 관련 기술을 선보였다.",
                        url="https://example.com/tech",
                    ),
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await get_stock_issue_news(
            "현대로템",
            direction="down",
            client=client,
        )

    assert items
    assert all(item["filter_fallback"] is True for item in items)
    assert all(item["has_direction_evidence"] is False for item in items)


@pytest.mark.asyncio
async def test_get_stock_issue_news_fetches_query_variants_concurrently(monkeypatch):
    monkeypatch.setattr("app.repositories.news.settings.naver_client_id", "client-id")
    monkeypatch.setattr(
        "app.repositories.news.settings.naver_client_secret",
        "client-secret",
    )

    active = 0
    max_active = 0
    queries: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        queries.append(request.url.params["query"])
        await asyncio.sleep(0.01)
        active -= 1
        query = request.url.params["query"]
        return httpx.Response(
            200,
            json={
                "items": [
                    _news_item(
                        title=f"{query} 호재 상승",
                        description="신규 수주와 실적 개선 기대가 있다.",
                        url=f"https://example.com/{len(queries)}",
                    )
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await get_stock_issue_news(
            "삼성전자",
            direction="up",
            client=client,
        )

    assert max_active > 1
    assert set(queries) == {"삼성전자", "삼성전자 주가", "삼성전자 상승"}
    assert items
