"""pgvector 기반 RAG 검색 + 간단 키워드 보정."""

import json
import logging
import re

from app import embeddings

logger = logging.getLogger("app.retrieval")


SYNONYM_MAP = {
    "수강": ["수강신청", "예비수강신청", "수강정정", "수강과목포기"],
    "수강신청": ["예비수강신청", "수강정정", "수강학점"],
    # "졸업" 하나에 "외국어능력 졸업인증"까지 얹으면, 외국어 인증과 무관한 일반
    # 졸업요건/학점 질문("23학번 졸업요건 알려줘")까지 임베딩이 외국어인증 문서
    # 쪽으로 쏠려 정작 학과 이수학점 문서가 밀려나는 문제가 있었다. 외국어 관련
    # 확장은 "외국어" 키에서만 하도록 분리한다.
    "졸업": ["졸업요건", "졸업학점", "졸업인증"],
    "졸업학점": ["졸업요건", "전공필수", "전공선택", "교양필수"],
    "복학": ["복학기간", "휴학연기", "학적변동"],
    "휴학": ["미등록휴학", "등록휴학", "휴학연기", "학기중휴학"],
    "사회봉사": ["봉사활동", "30시간", "P/F", "졸업인증"],
    "봉사": ["사회봉사", "봉사활동", "30시간"],
    "전과": ["전공변경", "전과신청기간"],
    "재입학": ["재입학신청기간", "제적", "퇴학"],
    "외국어": ["외국어능력 졸업인증", "국제어학원"],
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def tokenize(text: str) -> list[str]:
    text = normalize(text)
    tokens = re.findall(r"[가-힣a-zA-Z0-9]+", text)

    stopwords = {
        "언제",
        "뭐야",
        "무엇",
        "어떻게",
        "알려줘",
        "궁금해",
        "관련",
        "대해",
        "좀",
        "나는",
        "제가",
        "하면",
        "되나요",
    }

    return [token for token in tokens if len(token) >= 2 and token not in stopwords]


# 이 챗봇은 인공지능학과(구 AI·소프트웨어학부) 학생 전용이다. 질문에 학과명이 없으면
# "졸업요건 알려줘"처럼 학과 무관 표현이 타 학과에도 적용되는 범용 문서(졸업 안내,
# 외국어인증 등) 쪽으로만 임베딩이 쏠려, 정작 우리 학과 전용 구조화 문서(예: 학과별
# 이수학점 기준)가 밀려나는 문제가 있다. 학과명이 없을 때만 암묵적으로 붙여준다.
_DEPARTMENT_ALIASES = ("인공지능학과", "소프트웨어학과", "AI학과")


def _mentions_department(query: str) -> bool:
    return any(name in query for name in _DEPARTMENT_ALIASES)


def expand_query(query: str) -> str:
    expanded_terms = []

    for key, values in SYNONYM_MAP.items():
        if key in query:
            expanded_terms.extend(values)

    if not _mentions_department(query):
        expanded_terms.append("인공지능학과")

    if not expanded_terms:
        return query

    return f"{query} {' '.join(expanded_terms)}"


def deduplicate_hits(hits: list[dict]) -> list[dict]:
    seen = set()
    unique_hits = []

    for hit in hits:
        key = (
            hit.get("source"),
            hit.get("page"),
            normalize(hit.get("content", ""))[:120],
        )

        if key in seen:
            continue

        seen.add(key)
        unique_hits.append(hit)

    return unique_hits


_SELECT_COLS = (
    "source, page, content, category_l1, category_l2, priority, academic_year, keywords, "
    "1 - (embedding <=> %s::vector) AS vector_score"
)


def _fetch_candidates(
    conn,
    qlit: str,
    candidates: int,
    category_l1: str | None,
    academic_year: int | None = None,
):
    """pgvector 유사도 상위 후보 조회. category_l1 지정 시 해당 카테고리로 필터.
    academic_year 지정 시 '해당 년도 또는 년도무관(NULL)' 문서만 대상으로 한다
    (학번-aware: 다른 학번 전용 문서가 섞여 인용되는 것을 막는다).
    is_active=TRUE 문서만 대상으로 한다(멘토링 결과 §9)."""
    # SELECT의 score용 %s(qlit) → WHERE의 필터값들 → ORDER BY의 %s(qlit) → LIMIT
    # 순서로 파라미터를 맞춰 조립한다.
    conds = ["is_active = TRUE"]
    filter_params: list = []
    if category_l1:
        conds.append("category_l1 = %s")
        filter_params.append(category_l1)
    if academic_year is not None:
        conds.append("(academic_year = %s OR academic_year IS NULL)")
        filter_params.append(academic_year)
    where = " AND ".join(conds)
    return conn.execute(
        f"""
        SELECT {_SELECT_COLS}
        FROM documents
        WHERE {where}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (qlit, *filter_params, qlit, candidates),
    ).fetchall()


def _fetch_candidates_multi(
    conn, qlit: str, candidates: int, categories: list[str], academic_year: int | None = None
):
    """카테고리별로 개별 조회 후 합친다.

    category_l1 IN (...) 한 번에 조회하면 벡터 유사도가 조금이라도 높은
    카테고리가 상위를 독식해 다른 후보 카테고리 문서가 아예 안 들어올 수 있다.
    각 카테고리에서 최소 `candidates`개씩은 보장해 recall을 확보한다.
    """
    rows = []
    for cat in categories:
        rows.extend(_fetch_candidates(conn, qlit, candidates, cat, academic_year))
    return rows


def search(
    conn,
    query: str,
    k: int = 4,
    candidates: int = 12,
    category_l1: list[str] | str | None = None,
    academic_year: int | None = None,
    session_id: str | None = None,
) -> list[dict]:
    """질의와 가장 유사한 문서 청크 반환.

    1. query를 확장한다.
    2. pgvector로 후보 문서를 넉넉히 가져온다.
       - category_l1에 여러 카테고리가 지정되면 카테고리별로 개별 조회 후 병합한다.
         (하나의 category_l1만으로는 제도 설명과 일정 데이터가 다른 카테고리에
         분산 저장된 복합 질문을 놓칠 수 있어, router가 후보 카테고리를 여러 개
         넘길 수 있게 확장했다.)
       - 안전망: 카테고리 필터 결과가 비면 전체에서 다시 검색(오분류로 답을 놓치지 않도록).
    3. 중복 문서를 제거한다.
    4. lightweight reranker(vector/keyword/category/priority/recency)로 재정렬한다.
    """
    from app.services import reranker  # 지연 임포트(순환 방지)

    if isinstance(category_l1, str):
        category_l1 = [category_l1]
    requested_categories = category_l1

    expanded_query = expand_query(query)
    qvec = embeddings.embed_query(expanded_query)

    qlit = "[" + ",".join(map(str, qvec)) + "]"

    if requested_categories:
        rows = _fetch_candidates_multi(conn, qlit, candidates, requested_categories, academic_year)
    else:
        rows = _fetch_candidates(conn, qlit, candidates, None, academic_year)

    used_categories = requested_categories
    used_academic_year = academic_year
    fallback = False
    if academic_year is not None and not rows:
        # 해당 년도(+년도무관) 문서가 하나도 없음 → 년도 필터를 풀어 재검색.
        # (아직 그 학번 데이터가 적재되기 전이면 최소한 현행 문서라도 답하게 한다.)
        if requested_categories:
            rows = _fetch_candidates_multi(conn, qlit, candidates, requested_categories, None)
        else:
            rows = _fetch_candidates(conn, qlit, candidates, None, None)
        used_academic_year = None
        fallback = True
    if requested_categories and not rows:
        # 카테고리 필터로도 아무것도 못 찾음 → 전체 검색으로 폴백
        rows = _fetch_candidates(conn, qlit, candidates, None, None)
        used_categories = None
        used_academic_year = None
        fallback = True

    hits = [
        {
            "source": row[0],
            "page": row[1],
            "content": row[2],
            "category_l1": row[3],
            "category_l2": row[4],
            "priority": row[5],
            "academic_year": row[6],
            "keywords": row[7],
            "vector_score": float(row[8]),
        }
        for row in rows
    ]

    hits = deduplicate_hits(hits)

    # category_score()는 "후보 리스트 안에서 몇 번째인지"로 채점하므로 리스트
    # 전체를 넘겨야 한다. 문자열 하나(예: primary_category)만 넘기면 파이썬의
    # `in`이 부분 문자열 매칭으로 동작해 "course"가 "academic_calendar"에
    # 없다고 오판되는 등 다른 카테고리 문서가 부당하게 낮은 점수를 받는다.
    hits = reranker.rerank(query, used_categories, hits)
    hits = hits[:k]

    logger.info(
        json.dumps(
            {
                "stage": "retrieval",
                "session_id": session_id,
                "question": query,
                "requested_categories": requested_categories,
                "used_categories": used_categories,
                "requested_academic_year": academic_year,
                "used_academic_year": used_academic_year,
                "fallback": fallback,
                "selected": [
                    {
                        "source": hit["source"],
                        "category_l1": hit["category_l1"],
                        "category_l2": hit.get("category_l2"),
                        "vector_score": round(hit["vector_score"], 4),
                        "score": round(hit["score"], 4),
                    }
                    for hit in hits
                ],
            },
            ensure_ascii=False,
        )
    )

    return hits
