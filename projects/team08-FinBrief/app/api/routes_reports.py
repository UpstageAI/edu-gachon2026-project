"""Report execution and lookup endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.agents.pipeline import run_morning_pipeline
from app.api.dependencies import (
    get_embedding_provider,
    get_ingestion_repository,
    get_repository_bundle,
)
from app.core.schemas import BatchRunResult
from app.core.evaluations import eval_summary
from app.core.config import Settings, get_settings
from app.repositories.protocols import RepositoryBundle
from app.services.report_explanation_service import get_or_build_report_explanation
from app.services.report_result_service import get_report_result
from app.services.topic_ingestion import TopicIngestionOptions, TopicIngestionResult, ingest_topics


router = APIRouter()
DISCLAIMER = "본 브리핑은 투자 조언이 아닌 참고용 정보입니다."


class ReportRunRequest(BaseModel):
    run_date: date | None = None
    dry_run: bool = True
    refresh_data: bool = False


def _summary(
    result: BatchRunResult,
    *,
    ingestion: TopicIngestionResult | None = None,
) -> dict[str, object]:
    generated = len([card for card in result.generated_cards if not card.cached])
    reused = len([card for card in result.generated_cards if card.cached])
    payload: dict[str, object] = {
        "run_id": result.run_id,
        "run_date": result.run_date.isoformat(),
        "status": result.status,
        "generated_cards": generated,
        "reused_cards": reused,
        "delivery_results": len(result.delivery_results),
        "trace_id": result.trace_id,
        "report_url": result.report.report_url if result.report else None,
        "disclaimer": result.report.disclaimer if result.report else DISCLAIMER,
        "errors": result.errors,
        "eval_summary": eval_summary(result.eval_results),
    }
    if ingestion is not None:
        payload["ingestion"] = ingestion.model_dump(mode="json")
    return payload


def _refresh_active_topics(
    repos: RepositoryBundle,
    *,
    run_date: date,
    ingestion: Any | None,
    embedding_provider: Any | None,
) -> TopicIngestionResult:
    if ingestion is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "INGESTION_REPOSITORY_UNAVAILABLE",
                "message": "Supabase ingestion repository is required for refresh_data.",
            },
        )

    seen: set[str] = set()
    topics = []
    for subscription in repos.subscriptions.list_active():
        if subscription.topic_id in seen:
            continue
        topics.append(repos.topics.get(subscription.topic_id))
        seen.add(subscription.topic_id)

    return ingest_topics(
        topics,
        ingestion=ingestion,
        run_date=run_date,
        embedding_provider=embedding_provider,
        options=TopicIngestionOptions(dry_run=False),
    )


@router.post("/reports/run")
def run_report(
    request: ReportRunRequest,
    settings: Settings = Depends(get_settings),
    repos: RepositoryBundle = Depends(get_repository_bundle),
    ingestion: Any | None = Depends(get_ingestion_repository),
    embedding_provider: Any | None = Depends(get_embedding_provider),
) -> dict[str, object]:
    run_date = request.run_date or date.today()
    ingestion_result = None
    if request.refresh_data:
        ingestion_result = _refresh_active_topics(
            repos,
            run_date=run_date,
            ingestion=ingestion,
            embedding_provider=embedding_provider,
        )

    result = run_morning_pipeline(
        repos,
        run_date=run_date,
        dry_run=request.dry_run,
        settings=settings,
    )
    return _summary(result, ingestion=ingestion_result)


@router.get("/reports/today")
def get_today_report(
    run_date: date | None = Query(default=None),
    repos: RepositoryBundle = Depends(get_repository_bundle),
) -> dict[str, object]:
    result = get_report_result(repos, run_date=run_date)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REPORT_NOT_FOUND", "message": "No report has been generated."},
        )
    return _summary(result)


@router.get("/reports/today/explanation")
def get_today_report_explanation(
    run_date: date | None = Query(default=None),
    max_focus: int = Query(default=3, ge=1, le=5),
    refresh: bool = Query(default=False),
    repos: RepositoryBundle = Depends(get_repository_bundle),
) -> dict[str, object]:
    result = get_report_result(repos, run_date=run_date)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REPORT_NOT_FOUND", "message": "No report has been generated."},
        )
    return get_or_build_report_explanation(
        repos,
        result=result,
        max_focus=max_focus,
        refresh=refresh,
    )
