"""Service wrapper for running the FinBrief LangGraph pipeline from APIs."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.agents.graph import graph
from app.core import langfuse_scores, observability
from app.core.config import Settings, get_settings
from app.core.evaluations import eval_summary, evaluate_batch_result
from app.core.schemas import (
    BatchRunResult,
    CardArtifact,
    DeliveryLog,
    FullReport,
    IndicatorValue,
    NewsEvidence,
    TopicAnalysis,
)
from app.repositories.protocols import RepositoryBundle


DISCLAIMER = "본 브리핑은 투자 조언이 아닌 참고용 정보입니다."
_LATEST_RESULTS: dict[date, BatchRunResult] = {}


def _indicator_from_state(item: dict[str, Any], run_date: date) -> IndicatorValue:
    current_value = float(item.get("value") or item.get("current_value") or 0)
    previous_value = item.get("prev", item.get("previous_value"))
    previous_float = float(previous_value) if previous_value is not None else None
    return IndicatorValue(
        indicator_id=str(item["indicator_id"]),
        name=str(item.get("name") or item["indicator_id"]),
        source="fixture",
        value_date=run_date,
        current_value=current_value,
        previous_value=previous_float,
        change_percent=item.get("change_pct", item.get("change_percent")),
        unit=item.get("unit"),
        missing=bool(item.get("missing", False)),
    )


def _card_from_state(
    repos: RepositoryBundle,
    item: dict[str, Any],
    run_date: date,
) -> CardArtifact:
    cached = repos.cards.get(str(item["topic_id"]), run_date)
    if cached is not None:
        return cached.model_copy(update={"cached": bool(item.get("cached", cached.cached))})

    headline = str(item.get("headline") or item.get("subtitle") or item["topic_id"])
    summary = str(item.get("lead") or item.get("body") or headline)
    evidence = [
        NewsEvidence.model_validate(evidence_item)
        for evidence_item in item.get("evidence", [])
    ]
    return CardArtifact(
        card_id=str(item.get("card_id") or f"card_{item['topic_id']}_{run_date:%Y%m%d}"),
        topic_id=str(item["topic_id"]),
        run_date=run_date,
        title=headline,
        image_url=item.get("image_url") or item.get("image_path"),
        analysis=TopicAnalysis(
            topic_id=str(item["topic_id"]),
            run_date=run_date,
            headline=headline,
            summary=summary,
            key_points=[summary],
            evidence=evidence,
            disclaimer=str(item.get("disclaimer") or DISCLAIMER),
        ),
        cached=bool(item.get("cached", False)),
    )


def _delivery_from_state(item: dict[str, Any]) -> DeliveryLog:
    return DeliveryLog(
        delivery_id=str(item["delivery_id"]),
        user_id=str(item["user_id"]),
        topic_id=item.get("topic_id"),
        card_id=item.get("card_id"),
        channel=item["channel"],
        status=item["status"],
        attempts=int(item.get("attempts", 0)),
    )


def _store_eval_results(repos: RepositoryBundle, results: list[Any]) -> int:
    try:
        repos.evals.insert_many(results)
        return len(results)
    except Exception:
        return 0


def run_morning_pipeline(
    repos: RepositoryBundle,
    *,
    run_date: date,
    run_id: str | None = None,
    dry_run: bool = True,
    send_report: bool = True,
    send_cards: bool = True,
    only_user: str | None = None,
    settings: Settings | None = None,
) -> BatchRunResult:
    runtime_run_id = run_id or f"run_{run_date:%Y%m%d}_mock"
    runtime_settings = settings or get_settings()
    with observability.report_trace(
        run_id=runtime_run_id,
        run_date=run_date.isoformat(),
        settings=runtime_settings,
        metadata={"dry_run": dry_run},
    ) as (trace_id, trace):
        final = graph.invoke(
            {
                "run_id": runtime_run_id,
                "run_date": run_date.isoformat(),
                "status": "queued",
                "trace_id": trace_id,
                "repositories": repos,
                "cards": [],
                "deliveries": [],
                "errors": [],
                "dry_run": dry_run,
                # Supabase/Upstage 실데이터 모드는 mock 비활성화 시에만 켠다.
                "live_data": not runtime_settings.enable_mock_data,
                # 발송 범위(배치 트리거 옵션)
                "deliver_report": send_report,
                "deliver_cards": send_cards,
                "only_external_user": only_user,
            }
        )
        report_indicators = final.get("report_indicators") or final.get("indicators", [])
        report_missing = final.get("report_missing_indicators") or final.get("missing_indicators", [])
        indicators = [
            _indicator_from_state(item, run_date)
            for item in report_indicators
        ]
        cards = [_card_from_state(repos, item, run_date) for item in final.get("cards", [])]
        deliveries = [_delivery_from_state(item) for item in final.get("deliveries", [])]
        report = FullReport(
            report_id=f"report_{run_date:%Y%m%d}",
            run_date=run_date,
            indicators=indicators,
            top_news=[],
            missing_indicators=[str(item) for item in report_missing],
            report_url=final.get("report_url"),
            disclaimer=DISCLAIMER,
        )
        result = BatchRunResult(
            run_id=runtime_run_id,
            run_date=run_date,
            status=final["status"],
            report=report,
            generated_cards=cards,
            delivery_results=deliveries,
            trace_id=final.get("trace_id"),
            errors=[str(item.get("message", item)) for item in final.get("errors", [])],
        )
        eval_results = evaluate_batch_result(result, settings=runtime_settings)
        result = result.model_copy(update={"eval_results": eval_results})
        stored_evals = _store_eval_results(repos, eval_results)
        exported_scores = langfuse_scores.score_eval_results(eval_results, settings=runtime_settings)
        stored_report_result = True
        try:
            repos.reports.upsert(result)
        except Exception as exc:
            stored_report_result = False
            result = result.model_copy(
                update={"errors": [*result.errors, f"REPORT_RESULT_STORE_FAILED: {exc}"]}
            )
        trace.update(
            output={
                "status": final.get("status"),
                "generated_count": final.get("generated_count"),
                "reused_count": final.get("reused_count"),
                "error_count": len(final.get("errors", [])),
                "eval_summary": eval_summary(eval_results),
                "stored_eval_results": stored_evals,
                "stored_report_result": stored_report_result,
                "exported_langfuse_scores": exported_scores,
            }
        )
    _LATEST_RESULTS[run_date] = result
    return result


def get_latest_result(run_date: date | None = None) -> BatchRunResult | None:
    if run_date is not None:
        return _LATEST_RESULTS.get(run_date)
    if not _LATEST_RESULTS:
        return None
    return _LATEST_RESULTS[max(_LATEST_RESULTS)]


def get_user_cards(
    repos: RepositoryBundle,
    *,
    user_id: str,
    run_date: date,
) -> list[CardArtifact]:
    user = repos.users.get_or_create("discord", user_id)
    cards: list[CardArtifact] = []
    for subscription in repos.subscriptions.list_by_user(user.user_id):
        card = repos.cards.get(subscription.topic_id, run_date)
        if card is not None:
            cards.append(card)
    return cards


def reset_latest_results() -> None:
    _LATEST_RESULTS.clear()
