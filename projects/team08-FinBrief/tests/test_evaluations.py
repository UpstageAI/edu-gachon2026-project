from datetime import date

from app.core.evaluations import eval_run_rows, eval_summary, evaluate_batch_result
from app.core.schemas import (
    BatchRunResult,
    CardArtifact,
    FullReport,
    IndicatorValue,
    NewsEvidence,
    TopicAnalysis,
)
from app.repositories.memory import create_memory_repositories


def _indicator(indicator_id: str, value: float) -> IndicatorValue:
    return IndicatorValue(
        indicator_id=indicator_id,
        name=indicator_id,
        source="fixture",
        value_date=date(2026, 7, 14),
        current_value=value,
        previous_value=100.0,
        change_value=value - 100.0,
        change_percent=1.0,
        unit="pt",
    )


def _card(topic_id: str, *, evidence: bool = True) -> CardArtifact:
    items = []
    if evidence:
        items.append(
            NewsEvidence(
                news_id=f"news_{topic_id}",
                title=f"{topic_id} 관련 뉴스",
                source="연합뉴스",
                url="https://example.com/news",
                similarity=0.8,
                snippet="관련 지표와 뉴스 근거입니다.",
            )
        )
    return CardArtifact(
        card_id=f"card_{topic_id}",
        topic_id=topic_id,
        run_date=date(2026, 7, 14),
        title=f"{topic_id} 요약",
        image_url=f"/tmp/{topic_id}.png",
        analysis=TopicAnalysis(
            topic_id=topic_id,
            run_date=date(2026, 7, 14),
            headline=f"{topic_id} 변동",
            summary="시장 흐름을 요약했습니다.",
            key_points=["뉴스 근거 기반 요약입니다."],
            evidence=items,
            disclaimer="본 브리핑은 투자 조언이 아닌 참고용 정보입니다.",
        ),
    )


def _result() -> BatchRunResult:
    return BatchRunResult(
        run_id="run_eval",
        run_date=date(2026, 7, 14),
        status="completed",
        trace_id="trace_eval",
        report=FullReport(
            report_id="report_eval",
            run_date=date(2026, 7, 14),
            indicators=[
                _indicator("kospi", 101.0),
                _indicator("shanghai", float("nan")),
            ],
            top_news=[],
        ),
        generated_cards=[_card("topic_btc", evidence=True), _card("topic_nasdaq", evidence=False)],
    )


def test_evaluate_batch_result_builds_run_level_quality_checks():
    results = evaluate_batch_result(_result())

    by_name = {item.eval_name: item for item in results}
    assert set(by_name) == {
        "safety.disclaimer",
        "safety.forbidden_terms",
        "rag.evidence_coverage",
        "data.numeric_consistency",
        "format.card_schema",
    }
    assert by_name["safety.disclaimer"].passed is True
    assert by_name["safety.forbidden_terms"].passed is True
    assert by_name["rag.evidence_coverage"].passed is False
    assert by_name["rag.evidence_coverage"].score == 0.5
    assert by_name["data.numeric_consistency"].passed is False
    assert "shanghai" in by_name["data.numeric_consistency"].result["invalid_indicators"]
    assert by_name["format.card_schema"].passed is True
    assert all(item.run_id == "run_eval" for item in results)
    assert all(item.trace_id == "trace_eval" for item in results)


def test_eval_summary_and_rows_are_storage_ready():
    results = evaluate_batch_result(_result())

    summary = eval_summary(results)
    rows = eval_run_rows(results)

    assert summary["total"] == 5
    assert summary["passed"] == 3
    assert summary["failed"] == 2
    assert rows[0]["run_id"] == "run_eval"
    assert rows[0]["trace_id"] == "trace_eval"
    assert rows[0]["run_date"] == "2026-07-14"
    assert rows[0]["eval_name"] in summary["scores"]


def test_memory_eval_repository_records_results():
    repos = create_memory_repositories()
    results = evaluate_batch_result(_result())

    repos.evals.insert_many(results)
    stored = repos.evals.list_by_run("run_eval")

    assert [item.eval_name for item in stored] == [item.eval_name for item in results]
    assert stored[0].trace_id == "trace_eval"
