"""Day2 Mock 백문백답 저장소.

data/mock_law_qa.json을 읽어 keyword 기반 mock 검색을 제공한다.
파트 A의 retrieve 노드가 search_law_qa()를 호출한다.
저장소는 문서 반환만 하며, 0건 시 응답 처리(fallback)는 파트 A 담당이다.
Day3에 ChromaDB 검색으로 교체된다.
"""

import json
from pathlib import Path

from app.schemas.document import RetrievedDocument

# 이 파일(app/repositories/) 기준 두 단계 위가 프로젝트 루트
_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "mock_law_qa.json"

_MIN_TOKEN_LENGTH = 2


def load_law_qa() -> list[RetrievedDocument]:
    """data/mock_law_qa.json을 읽어 RetrievedDocument 리스트로 반환한다.

    파일이 없거나 JSON이 깨진 경우 예외(FileNotFoundError, JSONDecodeError)를
    그대로 올린다. "검색 결과 없음"과 "데이터 로드 실패"를 섞지 않는다.
    """
    with _DATA_PATH.open(encoding="utf-8") as f:
        raw_items = json.load(f)
    return [RetrievedDocument(**item) for item in raw_items]


def _tokenize(query: str) -> set[str]:
    """공백 분리 후 구두점을 떼고 2글자 이상 토큰만 남긴다."""
    tokens = (token.strip("?!.,~ ") for token in query.split())
    return {token for token in tokens if len(token) >= _MIN_TOKEN_LENGTH}


def search_law_qa(query: str, top_k: int = 3) -> list[RetrievedDocument]:
    """keyword 기반 mock 검색.

    query 토큰이 문서 question/answer에 부분 문자열로 포함된 개수를 세어
    매칭 수 내림차순으로 최대 top_k건 반환한다.
    매칭 문서가 없으면 빈 리스트를 반환하고 예외를 던지지 않는다.
    """
    tokens = _tokenize(query)
    if not tokens:
        return []

    scored: list[tuple[int, RetrievedDocument]] = []
    for document in load_law_qa():
        target = f"{document.question} {document.answer}"
        matched = sum(1 for token in tokens if token in target)
        if matched > 0:
            scored.append((matched, document))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [document for _, document in scored[:top_k]]
