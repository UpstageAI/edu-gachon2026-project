"""Lightweight reranker (멘토링 결과 §8).

pgvector가 가져온 후보 문서들을 여러 신호를 조합해 다시 정렬한다.

final_score =
    vector_score   * 0.65
  + keyword_score  * 0.15
  + category_score * 0.10
  + priority_score * 0.05
  + recency_score  * 0.05

각 부분 점수는 0~1 로 정규화한다.
"""

from __future__ import annotations

from app import retrieval

W_VECTOR = 0.65
W_KEYWORD = 0.15
W_CATEGORY = 0.10
W_PRIORITY = 0.05
W_RECENCY = 0.05

# 최신성 기준 학년도. Date.now 미사용(환경 고정) — 데이터 최신 학년도에 맞춰 상수로 둔다.
LATEST_YEAR = 2026


def keyword_score(query: str, content: str, keywords: list[str] | None) -> float:
    """질문 토큰이 문서 content/keywords 에 얼마나 매칭되는지 (0~1)."""
    q_tokens = retrieval.tokenize(query)
    if not q_tokens:
        return 0.0
    haystack = retrieval.normalize(content)
    kw = {retrieval.normalize(k) for k in (keywords or [])}
    hit = 0
    for t in q_tokens:
        if t in haystack or t in kw:
            hit += 1
    return hit / len(q_tokens)


def priority_score(priority: int | None) -> float:
    """priority 1(핵심)=1.0, 2=0.6, 3+=0.3. (작을수록 중요)"""
    return {1: 1.0, 2: 0.6}.get(priority or 2, 0.3)


def recency_score(academic_year: int | None) -> float:
    """최신 학년도일수록 높게. 연도 없으면 중립 0.5."""
    if academic_year is None:
        return 0.5
    diff = LATEST_YEAR - academic_year
    if diff <= 0:
        return 1.0
    if diff == 1:
        return 0.7
    if diff == 2:
        return 0.5
    return 0.3


def category_score(predicted: list[str] | None, doc_category: str | None) -> float:
    """router가 넘긴 category 후보 리스트 기준으로 점수를 매긴다.

    - 예측 자체가 없으면(전체 검색) 중립 0.5.
    - 문서 카테고리가 후보 리스트 안에 있으면: 주 카테고리(리스트 첫 항목)는 1.0,
      함께 검색된 부 카테고리(예: 시간 신호로 추가된 academic_calendar)는 0.8.
    - 후보 리스트에 없으면 0.3 (완전히 0점으로 배제하지 않는다 — 카테고리 오분류로
      정답 문서가 전부 걸러지는 걸 막기 위한 최소한의 안전판).
    """
    if not predicted:
        return 0.5
    if doc_category not in predicted:
        return 0.3
    return 1.0 if doc_category == predicted[0] else 0.8


def rerank(query: str, predicted_category: list[str] | None, hits: list[dict]) -> list[dict]:
    """후보(hits)에 final_score 를 매기고 내림차순 정렬해 반환.

    각 hit 는 최소한 vector_score, content, category_l1, priority,
    academic_year, keywords 키를 가진다고 가정한다.
    """
    for h in hits:
        vs = float(h.get("vector_score", 0.0))
        ks = keyword_score(query, h.get("content", ""), h.get("keywords"))
        cs = category_score(predicted_category, h.get("category_l1"))
        ps = priority_score(h.get("priority"))
        rs = recency_score(h.get("academic_year"))
        h["keyword_score"] = ks
        h["category_score"] = cs
        h["priority_score"] = ps
        h["recency_score"] = rs
        h["score"] = (
            vs * W_VECTOR + ks * W_KEYWORD + cs * W_CATEGORY + ps * W_PRIORITY + rs * W_RECENCY
        )
    hits.sort(key=lambda item: item["score"], reverse=True)
    return hits
