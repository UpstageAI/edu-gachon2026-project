"""OpenAI 호환 API 응답의 토큰 사용량 처리."""

from typing import Any


def extract_token_usage(response: Any) -> dict[str, int] | None:
    """usage에서 실제로 제공된 표준 토큰 수만 추출한다."""
    if not isinstance(response, dict) or not isinstance(response.get("usage"), dict):
        return None

    usage = response["usage"]
    normalized: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            normalized[key] = value
    return normalized or None
