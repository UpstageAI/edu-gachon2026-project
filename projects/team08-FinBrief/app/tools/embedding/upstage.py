"""Upstage embedding helpers for FinBrief RAG."""

from __future__ import annotations

from collections.abc import Sequence

from app.core.config import Settings, get_settings
from app.core.schemas import NewsDocument, Topic


EMBEDDING_PASSAGE_MODEL = "solar-embedding-1-large-passage"
EMBEDDING_QUERY_MODEL = "solar-embedding-1-large-query"
EMBEDDING_MODEL = EMBEDDING_PASSAGE_MODEL
EMBEDDING_DIMENSIONS = 4096
UPSTAGE_EMBEDDINGS_URL = "https://api.upstage.ai/v1/solar/embeddings"


def embedding_model_for_kind(embedding_kind: str) -> str:
    """Return the Upstage embedding model for passage/query requests."""

    normalized_kind = embedding_kind.strip().casefold()
    if normalized_kind == "passage":
        return EMBEDDING_PASSAGE_MODEL
    if normalized_kind == "query":
        return EMBEDDING_QUERY_MODEL
    raise ValueError(f"unsupported embedding kind: {embedding_kind}")


def build_passage_text(document: NewsDocument) -> str:
    """Build passage text for storing a news document embedding."""

    tags = ", ".join(document.tags) if document.tags else "없음"
    summary = document.summary or document.title
    return "\n".join(
        [
            f"제목: {document.title}",
            f"요약: {summary}",
            f"출처: {document.source}",
            f"발행일: {document.published_at.date().isoformat()}",
            f"태그: {tags}",
        ]
    )


def build_topic_query_text(topic: Topic) -> str:
    """Build query text for retrieving topic-related news."""

    keywords = sorted(
        {
            keyword
            for mapping in topic.source_mapping
            for keyword in mapping.news_keywords
            if keyword
        }
    )
    keyword_text = ", ".join(keywords) if keywords else topic.name
    return "\n".join(
        [
            f"토픽: {topic.name}",
            f"키워드: {keyword_text}",
            "요청: 오늘 금융시장 브리핑에 필요한 관련 뉴스",
        ]
    )


def validate_embedding(
    embedding: Sequence[float],
    *,
    expected_dimensions: int = EMBEDDING_DIMENSIONS,
) -> list[float]:
    """Validate embedding dimensions before storing in pgvector."""

    vector = [float(value) for value in embedding]
    if len(vector) != expected_dimensions:
        raise ValueError(
            f"embedding dimension must be {expected_dimensions}, got {len(vector)}"
        )
    return vector


class UpstageEmbeddingProvider:
    """Small Upstage embedding API wrapper.

    The provider is intentionally thin so tests can use fake providers.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def embed(self, text: str, *, embedding_kind: str) -> list[float]:
        if self._settings.upstage_api_key is None:
            raise RuntimeError("UPSTAGE_API_KEY is required for embeddings")

        import httpx

        model = embedding_model_for_kind(embedding_kind)
        response = httpx.post(
            UPSTAGE_EMBEDDINGS_URL,
            headers={
                "Authorization": f"Bearer {self._settings.upstage_api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "input": text,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        embedding = payload["data"][0]["embedding"]
        return validate_embedding(embedding)

    def embed_passage(self, document: NewsDocument) -> list[float]:
        return self.embed(build_passage_text(document), embedding_kind="passage")

    def embed_query(self, topic: Topic) -> list[float]:
        return self.embed(build_topic_query_text(topic), embedding_kind="query")

    def embed_passages(self, documents: list, *, batch_size: int = 64) -> list:
        """여러 문서를 배치로 임베딩(문서 1건당 호출 1번 → 한 호출에 batch_size건).
        아침 1회 임베딩에서 ~500 호출을 ~8 호출로 줄여 레이트리밋을 방지한다.
        입력 순서와 정렬된 list 를 반환하며, 배치 실패분은 None."""
        texts = [build_passage_text(d) for d in documents]
        out: list = []
        for i in range(0, len(texts), batch_size):
            out.extend(self._embed_batch(texts[i:i + batch_size]))
        return out

    def _embed_batch(self, texts: list, *, attempts: int = 3) -> list:
        if not texts:
            return []
        if self._settings.upstage_api_key is None:
            raise RuntimeError("UPSTAGE_API_KEY is required for embeddings")

        import time

        import httpx

        for attempt in range(attempts):
            try:
                response = httpx.post(
                    UPSTAGE_EMBEDDINGS_URL,
                    headers={
                        "Authorization": f"Bearer {self._settings.upstage_api_key.get_secret_value()}",
                        "Content-Type": "application/json",
                    },
                    json={"model": EMBEDDING_PASSAGE_MODEL, "input": texts},
                    timeout=60,
                )
                response.raise_for_status()
                data = sorted(response.json()["data"], key=lambda item: item.get("index", 0))
                return [validate_embedding(item["embedding"]) for item in data]
            except Exception:
                if attempt < attempts - 1:
                    time.sleep(1.0 * (attempt + 1))
        return [None] * len(texts)   # 배치 최종 실패 → 다음 실행에서 재시도(백필)
