from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings
from app.core.http import log_external_api_error

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT_SECONDS = 3


class SupabaseFeedbackRepository:
    """추천 결과에 대한 사용자 피드백(엄지 업/다운)을 Supabase에 저장한다."""

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = (settings.supabase_url or "").rstrip("/")
        self._key = settings.supabase_key or ""

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url and self._key)

    async def save(
        self,
        *,
        session_id: str,
        message_id: str,
        trace_id: str | None,
        rating: str,
    ) -> bool:
        if not self.is_configured:
            return False

        headers = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        }
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS, headers=headers) as client:
                response = await client.post(
                    f"{self._base_url}/rest/v1/recommendation_feedback",
                    params={"on_conflict": "session_id,message_id"},
                    json={
                        "session_id": session_id,
                        "message_id": message_id,
                        "trace_id": trace_id,
                        "rating": rating,
                    },
                )
                response.raise_for_status()
                return True
        except Exception as exc:  # noqa: BLE001 - 피드백 저장 실패가 채팅을 막지 않게 함
            log_external_api_error(logger, "Supabase 추천 피드백 저장", exc)
            return False
