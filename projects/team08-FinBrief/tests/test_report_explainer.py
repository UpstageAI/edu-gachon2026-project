from datetime import date, datetime, timezone

from app.core.schemas import BatchRunResult, FullReport, IndicatorValue, NewsDocument
from app.repositories.memory import create_memory_repositories
from app.services.report_explainer import build_report_explanation, select_focus_items


def _indicator(
    indicator_id: str,
    name: str,
    value: float,
    previous: float,
    change_percent: float | None,
    unit: str,
    *,
    change_value: float | None = None,
    missing: bool = False,
) -> IndicatorValue:
    return IndicatorValue(
        indicator_id=indicator_id,
        name=name,
        source="fixture",
        value_date=date(2026, 7, 14),
        current_value=value,
        previous_value=previous,
        change_value=change_value,
        change_percent=change_percent,
        unit=unit,
        missing=missing,
    )


def _result() -> BatchRunResult:
    return BatchRunResult(
        run_id="run_20260714_mock",
        run_date=date(2026, 7, 14),
        status="completed",
        report=FullReport(
            report_id="report_20260714",
            run_date=date(2026, 7, 14),
            indicators=[
                _indicator("btc", "비트코인", 65000, 63000, 3.17, "USD", change_value=2000),
                _indicator("nasdaq", "나스닥", 18000, 17800, 1.12, "pt", change_value=200),
                _indicator("us10y", "미국채(10년)", 4.3, 4.33, None, "%", change_value=-0.03),
                _indicator("shanghai", "상해종합", float("nan"), 3200, None, "pt", missing=True),
            ],
            top_news=[],
            missing_indicators=["shanghai"],
            report_url="app/agents/out_reports/20260714/market_report_20260714.png",
        ),
    )


def test_select_focus_items_excludes_missing_and_sorts_large_moves():
    focus = select_focus_items(_result(), max_items=3)

    assert [item["indicator_id"] for item in focus] == ["btc", "nasdaq", "us10y"]
    assert all(item["indicator_id"] != "shanghai" for item in focus)
    assert focus[0]["value_text"] == "65,000.00 USD"
    assert focus[2]["change_text"] == "▼ 0.0300%p"


def test_build_report_explanation_attaches_rss_evidence_and_disclaimer(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    news = [
        NewsDocument(
            news_id="news_btc",
            title="비트코인 ETF 자금 유입 확대",
            source="연합뉴스",
            url="https://example.com/btc",
            published_at=datetime(2026, 7, 14, 1, 0, tzinfo=timezone.utc),
            summary="비트코인 현물 ETF로 자금이 유입됐다는 소식입니다.",
            tags=["비트코인", "BTC"],
        ),
        NewsDocument(
            news_id="news_nasdaq",
            title="대형 기술주 강세",
            source="SBS 뉴스",
            url="https://example.com/nasdaq",
            published_at=datetime(2026, 7, 14, 2, 0, tzinfo=timezone.utc),
            summary="AI 반도체 기대가 대형 기술주에 반영됐습니다.",
            tags=["나스닥", "기술주"],
        ),
    ]
    repos = create_memory_repositories(news_documents=news)

    payload = build_report_explanation(_result(), repos=repos, max_focus=2)

    assert payload["run_date"] == "2026-07-14"
    assert payload["focus_items"][0]["indicator_id"] == "btc"
    assert payload["focus_items"][0]["evidence_count"] >= 1
    assert "연합뉴스" in payload["reply"]
    assert "투자 조언이 아닌" in payload["reply"]


def test_build_report_explanation_falls_back_without_news(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    payload = build_report_explanation(_result(), repos=create_memory_repositories(), max_focus=1)

    assert payload["focus_items"][0]["evidence_count"] == 0
    assert "RSS 뉴스 근거가 아직 부족" in payload["reply"]
    assert "비트코인" in payload["reply"]
