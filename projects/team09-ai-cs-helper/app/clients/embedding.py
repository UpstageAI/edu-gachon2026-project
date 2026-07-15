"""
임베딩 관련 함수.
"""

import logging
from dataclasses import dataclass
from typing import Any

from app.clients.http import env, post_json
from app.clients.usage import extract_token_usage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingResult:
    """임베딩 벡터와 공급자가 반환한 토큰 사용량."""

    vector: list[float]
    model: str
    token_usage: dict[str, int] | None


def embedding_config(kind: str) -> tuple[str, str, str]:
    """(base_url, api_key, model)을 반환한다."""
    model_env = (
        "UPSTAGE_EMBEDDING_QUERY_MODEL" if kind == "query" else "UPSTAGE_EMBEDDING_PASSAGE_MODEL"
    )
    return env("UPSTAGE_BASE_URL").rstrip("/"), env("UPSTAGE_API_KEY"), env(model_env)


def embed(text: str, kind: str) -> list[float]:
    """텍스트를 임베딩한다. kind는 'query' 또는 'passage'."""
    return embed_with_usage(text, kind).vector


def embed_with_usage(text: str, kind: str) -> EmbeddingResult:
    """텍스트 임베딩과 토큰 사용량을 함께 반환한다."""
    base_url, api_key, model = embedding_config(kind)
    logger.debug("임베딩 요청: kind=%s model=%s 입력=%d자", kind, model, len(text))
    response = post_json(
        f"{base_url}/embeddings",
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        {"model": model, "input": text},
    )
    response_model = response.get("model") if isinstance(response, dict) else None
    actual_model = response_model if isinstance(response_model, str) and response_model else model
    return EmbeddingResult(
        vector=_extract_embedding(response),
        model=actual_model,
        token_usage=extract_token_usage(response),
    )


def _extract_embedding(response: Any) -> list[float]:
    """임베딩 응답에서 벡터만 안전하게 꺼낸다.

    에러 바디나 예상치 못한 형태일 때 KeyError/IndexError 대신
    원인이 드러나는 RuntimeError를 낸다.
    """
    if isinstance(response, dict) and response.get("error"):
        raise RuntimeError(f"Embedding error response: {response['error']}")
    try:
        return response["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.error("임베딩 응답 형식 오류: %r", response)
        raise RuntimeError(f"Unexpected embedding response shape: {response!r}") from exc
