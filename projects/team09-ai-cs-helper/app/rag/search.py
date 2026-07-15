"""
RAG 검색 로직.

질문 문자열을 임베딩한 뒤, Supabase에 저장된 문서와 코사인 유사도로 비교해 상위 문서를 반환한다.
"""

import logging
import math
from typing import Any

from app.clients.embedding import EmbeddingResult, embed_with_usage
from app.clients.supabase import fetch_documents, parse_embedding

logger = logging.getLogger(__name__)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """두 벡터의 코사인 유사도 계산."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def search_with_usage(
    query_text: str, top_k: int = 5
) -> tuple[list[tuple[float, dict[str, Any]]], EmbeddingResult]:
    """상위 문서와 질의 임베딩의 토큰 사용량을 함께 반환한다."""
    embedding_result = embed_with_usage(query_text, "query")
    docs = fetch_documents()
    scored = [
        (cosine_similarity(embedding_result.vector, parse_embedding(doc["embedding"])), doc)
        for doc in docs
        if doc.get("embedding") is not None
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    top = scored[:top_k]
    logger.info(
        "RAG 검색: 질의=%r 전체문서=%d 상위%d 최고점수=%.4f",
        query_text[:80],
        len(docs),
        len(top),
        top[0][0] if top else 0.0,
    )
    return top, embedding_result
