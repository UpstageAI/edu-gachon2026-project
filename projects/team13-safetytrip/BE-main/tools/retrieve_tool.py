"""
disaster_guidelines pgvector 유사도 검색 (retrieve 노드용).
질문은 solar-embedding-1-large-query로, 문서는 이미 -passage로 임베딩되어 있음
(같은 벡터 공간이라 서로 비교 가능).

실행: python tools/retrieve_tool.py "해양오염사고 발생하면 어떻게 대피해야 하나요"
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import psycopg2
from dotenv import load_dotenv

from tools.resilience import call_with_retry

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
UPSTAGE_API_KEY = os.getenv("UPSTAGE_API_KEY")
EMBEDDING_URL = "https://api.upstage.ai/v1/solar/embeddings"
QUERY_MODEL = "solar-embedding-1-large-query"

# 429(속도제한)/5xx(서버오류)/타임아웃/연결오류만 재시도 대상 (400 등 요청 자체 오류는 재시도 무의미)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class _RetryableHTTPStatus(Exception):
    pass


def _embed_query_once(text: str) -> list:
    headers = {"Authorization": f"Bearer {UPSTAGE_API_KEY}", "Content-Type": "application/json"}
    resp = requests.post(EMBEDDING_URL, headers=headers,
                        json={"input": text, "model": QUERY_MODEL}, timeout=15)  # ① timeout
    if resp.status_code in _RETRYABLE_STATUS:
        raise _RetryableHTTPStatus(f"status={resp.status_code}")
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def embed_query(text: str) -> list:
    """② 재시도(타임아웃/연결오류/429/5xx만) ③ 그래도 실패하면 ToolUnavailableError"""
    return call_with_retry(
        _embed_query_once, text,
        retryable_exceptions=(
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            _RetryableHTTPStatus,
        ),
        tool_name="embed_query(Solar Embedding)",
    )


def _query_db_once(embedding_str: str, top_k: int) -> list:
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)  # ① timeout
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, content, safety_cate_nm1, safety_cate_nm2, safety_cate_nm3,
                   source_dataset, embedding <=> %s::vector AS distance
            FROM disaster_guidelines
            ORDER BY distance ASC
            LIMIT %s
        """, (embedding_str, top_k))
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        conn.close()


def retrieve_guidelines(query: str, top_k: int = 5):
    """
    질문과 코사인 거리가 가까운 행동요령 top_k개를 반환.
    인덱스 없이 순차 스캔(현재 데이터 규모에서는 충분히 빠름).

    임베딩 API 또는 DB 호출이 재시도까지 다 실패하면 ToolUnavailableError가
    발생함 - 호출부(retrieve_node)가 이를 잡아서 빈 리스트로 처리하고,
    게이트가 자동으로 에스컬레이션하도록 우아하게 강등시킴.
    """
    query_embedding = embed_query(query)
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    rows = call_with_retry(
        _query_db_once, embedding_str, top_k,
        retryable_exceptions=(psycopg2.OperationalError,),
        tool_name="retrieve_guidelines(DB)",
    )

    results = []
    for r in rows:
        results.append({
            "id": r[0],
            "content": r[1],
            "cate_nm1": r[2],
            "cate_nm2": r[3],
            "cate_nm3": r[4],
            "source_dataset": r[5],
            "distance": float(r[6]),
        })
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('사용법: python tools/retrieve_tool.py "질문 내용"')
        sys.exit(1)

    query = sys.argv[1]
    results = retrieve_guidelines(query)

    print(f"\n=== 질문: {query} ===\n")
    for r in results:
        print(f"[distance={r['distance']:.4f}] {r['cate_nm1']} > {r['cate_nm2']} > {r['cate_nm3']}")
        print(f"  {r['content'][:150]}")
        print()