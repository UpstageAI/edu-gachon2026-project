"""Solar 토큰 → USD 비용 환산 — 단일 지점.

litellm·Langfuse 는 solar/upstage 단가표가 없어 cost 를 0 으로 남긴다
(Langfuse Metrics API 의 totalCost 도 0 으로 확인됨). 그래서 토큰 사용량에
Upstage 공식 단가(settings.usd_per_1m_*)를 곱해 여기서 직접 계산한다.
per-query 응답 메타(query_service)와 대시보드 KPI(metrics_service)가 공통으로 쓴다.

입력: input_tokens, output_tokens / 출력: USD 비용(float)
"""
from __future__ import annotations

from app.core.settings import settings


def token_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """입력·출력 토큰 수 → USD 비용 (Upstage Solar 단가 기준, 6자리 반올림)."""
    return round(
        (input_tokens * settings.usd_per_1m_input
         + output_tokens * settings.usd_per_1m_output) / 1_000_000,
        6,
    )
