"""chroma_law_repository 테스트 (파트B — 실데이터 기준).

chroma_db/ 적재본과 Upstage API 키가 있는 환경에서만 실행된다.
없는 환경(CI 등)에서는 전체 skip 처리한다.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings  # noqa: E402
from app.repositories import chroma_law_repository  # noqa: E402
from app.repositories.chroma_law_repository import get_source_url, search_law_qa  # noqa: E402
from app.schemas.document import RetrievedDocument  # noqa: E402

CHROMA_READY = (PROJECT_ROOT / "chroma_db").exists() and bool(settings.upstage_api_key)

pytestmark = pytest.mark.skipif(
    not CHROMA_READY,
    reason="chroma_db/ 또는 UPSTAGE_API_KEY 없음 — scripts/ingest_chroma.py와 .env를 먼저 준비",
)


def _stored_embedding(document_id: str) -> list[float]:
    collection = chroma_law_repository._get_collection()
    result = collection.get(ids=[document_id], include=["embeddings"])
    return result["embeddings"][0].tolist()


@pytest.fixture
def use_known_rent_embedding(monkeypatch):
    monkeypatch.setattr(
        chroma_law_repository,
        "_embed_query",
        lambda query: _stored_embedding("law_2482"),
    )


@pytest.fixture
def use_no_result_embedding(monkeypatch):
    monkeypatch.setattr(
        chroma_law_repository,
        "_embed_query",
        lambda query: [0.0] * len(_stored_embedding("law_2482")),
    )


def test_search_normal_question_returns_retrieved_documents(use_known_rent_embedding):
    results = search_law_qa("월세 계약 전에 뭘 확인해야 하나요?")
    assert len(results) >= 1
    assert all(isinstance(document, RetrievedDocument) for document in results)
    # 실데이터 id는 law_{백문일련번호} 형식이고 category는 CSV 원문 그대로다
    assert all(document.id.startswith("law_") for document in results)
    assert results[0].category == "부동산/임대차"


def test_search_no_result_question_returns_empty_list_without_error(use_no_result_embedding):
    results = search_law_qa("상속 포기 절차가 궁금해요")
    assert results == []


def test_search_top_k_limits_result_count(use_known_rent_embedding):
    results = search_law_qa("월세 계약 전에 뭘 확인해야 하나요?", top_k=1)
    assert len(results) <= 1


def test_get_source_url_returns_url_for_existing_document():
    url = get_source_url("law_2482")
    assert url is not None
    assert url.startswith(("http://", "https://"))


def test_get_source_url_returns_none_for_unknown_id():
    assert get_source_url("unknown_id") is None
