"""Postgres 기반 리뷰 저장소(ReviewStore 구현 중 하나).

리뷰 결과를 review_runs 테이블에 저장한다. 전체 결과는 JSONB 컬럼(payload)에 통째로
넣고, 조회/필터에 쓰는 몇몇 값(경로 이름, 모델 등급 등)만 별도 컬럼으로 복제해 둔다.
운영 환경(여러 인스턴스가 같은 DB 공유)용이다. factory.py의 ReviewStore를 만족한다.
"""

from __future__ import annotations

from typing import Any

from backend.app.core.schemas import ReviewResult


class PostgresReviewStore:
    """review_runs 테이블에 리뷰 결과를 저장/조회하는 Postgres 저장소."""

    def __init__(self, database_url: str) -> None:
        # DB 접속 문자열(예: postgresql://user:pass@host/db).
        self.database_url = database_url
        # 테이블/인덱스를 이미 만들었는지 기억해, 매번 다시 만들지 않기 위한 플래그.
        self._schema_ready = False

    def _connect(self) -> Any:
        """DB 커넥션을 새로 연다. psycopg(파이썬 Postgres 드라이버)를 지연 임포트한다."""
        try:
            import psycopg
        except ModuleNotFoundError as exc:  # pragma: no cover
            # psycopg가 설치돼 있지 않으면 설치 방법을 안내하며 실패시킨다.
            raise RuntimeError("psycopg is not installed. Run `pip install -e .`.") from exc
        return psycopg.connect(self.database_url)

    def ensure_schema(self) -> None:
        """필요한 테이블/인덱스를 (없으면) 만든다. 첫 호출에만 실제로 실행된다."""
        if self._schema_ready:
            return
        # with ... as: 컨텍스트 매니저. 블록을 벗어나면 커넥션/커서를 자동으로 정리한다.
        # conn = 커넥션, cur = 커서(SQL을 실행하는 창구).
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                # 리뷰 결과 저장 테이블. payload(JSONB)에 전체 결과를 담고,
                # 나머지 컬럼은 목록 조회/필터를 빠르게 하려고 뽑아 둔 값이다.
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS review_runs (
                        review_run_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        route_name TEXT NOT NULL,
                        model_tier TEXT NOT NULL,
                        overall_risk TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                # 중복 리뷰 판별(idempotency_key)을 빠르게 하기 위한 인덱스.
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_review_runs_idempotency
                    ON review_runs (idempotency_key)
                    """
                )
                # 최신순 목록 조회를 빠르게 하기 위한 인덱스.
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_review_runs_created_at
                    ON review_runs (created_at DESC)
                    """
                )
        # 이번 프로세스에서 스키마 준비가 끝났음을 표시(다음부터는 건너뛴다).
        self._schema_ready = True

    def healthcheck(self) -> None:
        """DB에 간단한 쿼리(SELECT 1)를 던져 접속이 살아 있는지 확인한다."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

    def save_review(self, result: ReviewResult) -> None:
        """리뷰 결과 하나를 저장한다(같은 ID면 갱신)."""
        try:
            # Jsonb: 파이썬 dict를 Postgres의 JSONB 값으로 안전하게 넘기기 위한 래퍼.
            from psycopg.types.json import Jsonb
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError("psycopg is not installed. Run `pip install -e .`.") from exc

        self.ensure_schema()
        payload = result.to_dict()
        with self._connect() as conn:
            with conn.cursor() as cur:
                # INSERT ... ON CONFLICT ... DO UPDATE = "upsert": 같은 review_run_id가
                # 이미 있으면 새로 넣지 않고 기존 행을 덮어쓴다(재실행 시 중복 방지).
                # %s 자리표시자에 아래 튜플 값들이 순서대로 안전하게 바인딩된다.
                cur.execute(
                    """
                    INSERT INTO review_runs (
                        review_run_id,
                        status,
                        idempotency_key,
                        route_name,
                        model_tier,
                        overall_risk,
                        payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (review_run_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        idempotency_key = EXCLUDED.idempotency_key,
                        route_name = EXCLUDED.route_name,
                        model_tier = EXCLUDED.model_tier,
                        overall_risk = EXCLUDED.overall_risk,
                        payload = EXCLUDED.payload
                    """,
                    (
                        result.review_run_id,
                        result.status,
                        result.idempotency_key,
                        result.route.name,
                        result.route.model_tier,
                        result.summary.overall_risk,
                        Jsonb(payload),
                    ),
                )

    def list_reviews(
        self,
        limit: int | None = None,
        route_name: str | None = None,
        model_tier: str | None = None,
    ) -> list[dict[str, object]]:
        """리뷰 목록을 최신순으로 조회한다(선택적으로 필터/개수 제한)."""
        self.ensure_schema()
        # 주어진 필터만큼 WHERE 조건과 바인딩 값(params)을 동적으로 쌓는다.
        conditions: list[str] = []
        params: list[object] = []
        if route_name is not None:
            conditions.append("route_name = %s")
            params.append(route_name)
        if model_tier is not None:
            conditions.append("model_tier = %s")
            params.append(model_tier)
        # 조건이 있을 때만 "WHERE a = %s AND b = %s" 형태의 절을 만든다.
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        limit_clause = "LIMIT %s" if limit is not None else ""
        if limit is not None:
            params.append(limit)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT payload
                    FROM review_runs
                    {where_clause}
                    ORDER BY created_at DESC
                    {limit_clause}
                    """,
                    params,
                )
                # fetchall()은 (payload,) 형태의 행들을 준다. row[0]으로 payload만 꺼낸다.
                return [row[0] for row in cur.fetchall()]

    def get_review(self, review_run_id: str) -> dict[str, object] | None:
        """ID로 리뷰 하나를 조회한다. 없으면 None."""
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM review_runs WHERE review_run_id = %s",
                    (review_run_id,),  # 값이 하나여도 튜플로 넘겨야 한다(끝의 쉼표).
                )
                # fetchone()은 첫 행 하나(또는 None)를 준다.
                row = cur.fetchone()
        return row[0] if row else None
