"""ChromaDB 기반 백문백답 검색 저장소 (파트B Day3).

파트 A의 nodes.py chroma 분기가 이 모듈의 search_law_qa를 호출한다(존재 기반 선택).
계약은 mock_law_repository와 동일하며 저장소는 문서 반환만 한다.

조용한 fallback 방지 규칙 (파트B_DAY3_작업지시 3절):
- import 시점에는 어떤 I/O도 하지 않는다 (지연 초기화).
- 저장소 미준비(chroma_db/ 없음, 컬렉션 없음/비어 있음, API 키 없음)는
  호출 시점에 RuntimeError를 올린다.
- "검색 결과 없음"(임계값 필터 후 0건)은 빈 리스트. 예외와 절대 섞지 않는다.
"""

from pathlib import Path
from typing import Optional

import chromadb
import requests

from app.core.config import settings
from app.core.routing import EXACT_DISTANCE_THRESHOLD
from app.schemas.document import RetrievedDocument

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHROMA_PATH = PROJECT_ROOT / "chroma_db"
COLLECTION_NAME = "law_qa"
EMBEDDING_URL = "https://api.upstage.ai/v1/embeddings"
EMBEDDING_MODEL = "embedding-query"  # 적재(embedding-passage)와 쌍을 이루는 질의용 모델

# 기존 exact 검색 계약용 임계값. Day5 라우팅의 최종 exact threshold와 동일하게 유지한다.
SCORE_THRESHOLD = EXACT_DISTANCE_THRESHOLD

_INGEST_GUIDE = "scripts/ingest_chroma.py를 먼저 실행하세요."

_collection = None  # 첫 호출 시 초기화 후 재사용


def _get_collection():
    """law_qa 컬렉션을 지연 초기화로 얻는다. 미준비 상태면 RuntimeError."""
    global _collection
    if _collection is not None:
        return _collection

    if not CHROMA_PATH.exists():
        raise RuntimeError(f"chroma_db/가 없습니다. {_INGEST_GUIDE}")

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception as exc:
        raise RuntimeError(f"{COLLECTION_NAME} 컬렉션이 없습니다. {_INGEST_GUIDE}") from exc
    if collection.count() == 0:
        raise RuntimeError(f"{COLLECTION_NAME} 컬렉션이 비어 있습니다. {_INGEST_GUIDE}")

    _collection = collection
    return collection


def _embed_query(text: str) -> list[float]:
    """질문을 Upstage Embedding API로 벡터화한다."""
    if not settings.upstage_api_key:
        raise RuntimeError("UPSTAGE_API_KEY가 비어 있습니다. .env를 설정하세요.")
    response = requests.post(
        EMBEDDING_URL,
        headers={"Authorization": f"Bearer {settings.upstage_api_key}"},
        json={"model": EMBEDDING_MODEL, "input": text},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]


def search_law_qa_raw(query: str, top_k: int = 3) -> list[RetrievedDocument]:
    """ChromaDB raw top-k 벡터 검색.

    - query를 임베딩해 law_qa 컬렉션에서 top_k 검색한다.
    - cosine distance를 유지해 라우팅 계층이 threshold 구간을 직접 판정하게 한다.
    - metadata + document 본문으로 RetrievedDocument를 복원해 반환한다.
    """
    collection = _get_collection()
    result = collection.query(
        query_embeddings=[_embed_query(query)],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    retrieved: list[RetrievedDocument] = []
    for text, metadata, distance in zip(
        result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        # 적재 형식이 question + "\n" + answer 이므로 첫 줄 이후가 answer다
        answer = text.split("\n", 1)[1] if "\n" in text else text
        retrieved.append(
            RetrievedDocument(
                id=metadata["id"],
                question=metadata["question"],
                answer=answer,
                category=metadata["category"],
                distance=float(distance),
                source_url=metadata.get("source_url") or None,
            )
        )
    return retrieved


def search_law_qa(query: str, top_k: int = 3) -> list[RetrievedDocument]:
    """기존 계약용 exact 검색.

    현재 sync/stream 경로가 라우팅 분리 전에도 낮은 관련도 문서를 근거로 쓰지 않도록
    exact threshold 필터 동작은 유지한다. Day5 답변 라우팅은 search_law_qa_raw()를 사용한다.
    """
    return [
        document
        for document in search_law_qa_raw(query, top_k=top_k)
        if document.distance is not None and document.distance <= SCORE_THRESHOLD
    ]


def get_source_url(document_id: str) -> Optional[str]:
    """문서 id로 원문링크(source_url metadata)를 조회한다.

    - 파트 A의 generate/output_guardrail이 답변 끝 링크 부착에 사용한다.
      (RetrievedDocument 스키마를 바꾸지 않고 링크를 전달하기 위한 별도 헬퍼)
    - 존재하지 않는 id 또는 source_url이 없는 문서면 None.
    - 저장소 미준비 시에는 기존 규칙대로 RuntimeError (조용한 실패 금지).
    """
    collection = _get_collection()
    result = collection.get(ids=[document_id])
    if not result["ids"]:
        return None
    return result["metadatas"][0].get("source_url") or None
