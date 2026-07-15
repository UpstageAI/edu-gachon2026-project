"""외부 데이터 접근 계층 (pykrx·네이버·DART·Supabase)."""

from typing import Any

from loguru import logger

from app.core.config import settings

_supabase_client: Any | None = None


async def get_supabase_client() -> Any:
    """애플리케이션 전체에서 공유하는 Supabase 비동기 클라이언트."""
    global _supabase_client

    if _supabase_client is None:
        if not settings.supabase_url or not settings.supabase_key:
            raise RuntimeError("SUPABASE_URL과 SUPABASE_KEY가 필요합니다.")

        from supabase import acreate_client

        _supabase_client = await acreate_client(
            settings.supabase_url,
            settings.supabase_key,
        )
        logger.info("Supabase 비동기 클라이언트 초기화 완료")
    return _supabase_client
