"""Topic-scoped ingestion endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_embedding_provider,
    get_ingestion_repository,
    get_repository_bundle,
)
from app.repositories.protocols import RepositoryBundle, RepositoryNotFoundError
from app.services.topic_ingestion import (
    TopicIngestionOptions,
    TopicIngestionResult,
    ingest_topics,
)


router = APIRouter()


class TopicIngestionRequest(TopicIngestionOptions):
    run_date: date | None = None


def _error_detail(error: Exception | str, code: str) -> dict[str, str]:
    return {"code": code, "message": str(error)}


@router.post("/topics/{topic_id}/ingest")
def ingest_topic(
    topic_id: str,
    request: TopicIngestionRequest,
    repos: RepositoryBundle = Depends(get_repository_bundle),
    ingestion: Any | None = Depends(get_ingestion_repository),
    embedding_provider: Any | None = Depends(get_embedding_provider),
) -> dict[str, object]:
    try:
        topic = repos.topics.get(topic_id)
    except RepositoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error_detail(exc, exc.code),
        ) from exc

    if ingestion is None and not request.dry_run:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error_detail(
                "Supabase ingestion repository is unavailable in mock mode.",
                "INGESTION_REPOSITORY_UNAVAILABLE",
            ),
        )

    options = TopicIngestionOptions(
        include_indicators=request.include_indicators,
        include_news=request.include_news,
        include_embeddings=request.include_embeddings,
        dry_run=request.dry_run,
        since_days=request.since_days,
    )
    result: TopicIngestionResult = ingest_topics(
        [topic],
        ingestion=ingestion,
        run_date=request.run_date or date.today(),
        embedding_provider=embedding_provider,
        options=options,
    )
    return result.model_dump(mode="json")
