from datetime import date

from app.core.schemas import BatchRunResult, FullReport, IndicatorValue
from app.repositories.memory import create_memory_repositories
from app.services.report_explanation_service import get_or_build_report_explanation
from app.services.report_result_service import get_report_result, store_report_result


def _result() -> BatchRunResult:
    run_date = date(2026, 7, 14)
    return BatchRunResult(
        run_id="run_20260714_share",
        run_date=run_date,
        status="completed",
        trace_id="trace_report_share",
        report=FullReport(
            report_id="report_20260714",
            run_date=run_date,
            indicators=[
                IndicatorValue(
                    indicator_id="btc",
                    name="비트코인",
                    source="fixture",
                    value_date=run_date,
                    current_value=65000,
                    previous_value=63000,
                    change_value=2000,
                    change_percent=3.17,
                    unit="USD",
                )
            ],
            top_news=[],
            report_url="/reports/market_report_20260714.png",
        ),
    )


def test_memory_report_result_repository_shares_report_after_memory_reset(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    repos = create_memory_repositories()
    result = _result()

    store_report_result(repos, result)

    restored = get_report_result(repos, run_date=result.run_date)
    assert restored is not None
    assert restored.run_id == result.run_id
    assert restored.trace_id == "trace_report_share"
    assert restored.report is not None
    assert restored.report.report_url == "/reports/market_report_20260714.png"


def test_report_explanation_service_caches_payload(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    repos = create_memory_repositories()
    result = _result()
    store_report_result(repos, result)

    first = get_or_build_report_explanation(repos, result=result, max_focus=1)
    second = get_or_build_report_explanation(repos, result=result, max_focus=1)

    assert first["cached"] is False
    assert second["cached"] is True
    assert second["run_id"] == result.run_id
    assert second["reply"] == first["reply"]
