"""RAG 검색 리포지토리 (pgvector). 병합 시 이 구현만 Supabase로 교체하면 됨."""

import asyncio

from app import db, retrieval


class RagRepository:
    async def search_similar(
        self,
        query: str,
        k: int = 4,
        category_l1: list[str] | str | None = None,
        academic_year: int | None = None,
        session_id: str | None = None,
    ) -> list[dict]:
        def _search():
            conn = db.connect()
            try:
                return retrieval.search(
                    conn,
                    query,
                    k=k,
                    category_l1=category_l1,
                    academic_year=academic_year,
                    session_id=session_id,
                )
            finally:
                conn.close()

        return await asyncio.to_thread(_search)

    async def available_academic_years(self) -> set[int]:
        """문서에 실제 태깅된 교육과정 년도 집합(년도무관 NULL 제외).
        학번 → 적용 년도 매핑에 쓴다."""

        def _years():
            conn = db.connect()
            try:
                rows = conn.execute(
                    "SELECT DISTINCT academic_year FROM documents WHERE academic_year IS NOT NULL"
                ).fetchall()
                return {int(r[0]) for r in rows}
            finally:
                conn.close()

        return await asyncio.to_thread(_years)


_repo: RagRepository | None = None


def get_rag_repository() -> RagRepository:
    global _repo
    if _repo is None:
        _repo = RagRepository()
    return _repo
