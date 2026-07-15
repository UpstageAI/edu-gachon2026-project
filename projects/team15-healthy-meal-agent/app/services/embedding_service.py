"""
app/services/embedding_service.py
Upstage 임베딩 호출. 검색문/문서를 4096차원 벡터로 변환한다.

Upstage는 비대칭 임베딩 권장:
  - 저장할 음식(문서) → embedding-passage
  - 사용자 검색문(질의) → embedding-query
테스트에서 mock하기 쉽도록 함수 경계를 분리한다.
"""

import os

from dotenv import load_dotenv

load_dotenv()

_API_BASE = "https://api.upstage.ai/v1"
EMBED_DIM = 4096  # Upstage solar-embedding-1-large 계열 실측 차원


def _embed(text: str, model: str) -> list[float]:
    import litellm

    response = litellm.embedding(
        model="openai/" + model,
        input=[text],
        api_key=os.getenv("UPSTAGE_API_KEY"),
        api_base=_API_BASE,
        timeout=30,  # 무한 대기 방지
        num_retries=2,
    )
    return response.data[0]["embedding"]


def embed_query(text: str) -> list[float]:
    """사용자 검색문 → 4096 벡터 (매 요청 시 호출)."""
    return _embed(text, "embedding-query")


def embed_passage(text: str) -> list[float]:
    """저장할 음식 문서 → 4096 벡터 (적재 시 1회 호출)."""
    return _embed(text, "embedding-passage")
