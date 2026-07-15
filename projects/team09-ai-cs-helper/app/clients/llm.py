"""
LiteLLM 프록시를 통한 llm 호출 클라이언트.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any

from app.clients.http import LLM_TIMEOUT, env, post_json
from app.clients.usage import extract_token_usage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMResult:
    """LLM 응답 본문과 공급자가 반환한 토큰 사용량."""

    content: str
    model: str
    token_usage: dict[str, int] | None


def litellm_base_url() -> str:
    """LiteLLM 엔드포인트 base URL을 결정한다."""
    base_url = os.getenv("LITELLM_BASE_URL", "http://localhost:4000/v1").strip()
    return base_url.rstrip("/")


def _extract_content(response: Any) -> str:
    """LiteLLM 응답에서 assistant content만 안전하게 꺼낸다.

    HTTP 200에 에러 바디를 주거나(예: rate limit) 형태가 다를 때
    KeyError/IndexError 대신 원인이 드러나는 RuntimeError를 낸다.
    """
    if isinstance(response, dict) and response.get("error"):
        raise RuntimeError(f"LLM error response: {response['error']}")
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.error("LLM 응답 형식 오류: %r", response)
        raise RuntimeError(f"Unexpected LLM response shape: {response!r}") from exc
    if not content:
        logger.error("LLM 응답 content가 비어 있음: %r", response)
        raise RuntimeError("LLM returned empty content")
    return content


def chat_with_usage(messages: list[dict[str, str]], model: str | None = None) -> LLMResult:
    """messages를 보내 응답 본문과 토큰 사용량을 함께 반환한다."""
    base_url = litellm_base_url()
    used_model = model or env("LITELLM_CHAT_MODEL")
    logger.info("LLM 요청: model=%s base_url=%s messages=%d", used_model, base_url, len(messages))
    response = post_json(
        f"{base_url}/chat/completions",
        {
            "Authorization": f"Bearer {env('LITELLM_MASTER_KEY')}",
            "Content-Type": "application/json",
        },
        {
            "model": used_model,
            "messages": messages,
        },
        timeout=LLM_TIMEOUT,
    )
    content = _extract_content(response)
    token_usage = extract_token_usage(response)
    response_model = response.get("model") if isinstance(response, dict) else None
    actual_model = (
        response_model if isinstance(response_model, str) and response_model else used_model
    )
    logger.info("LLM 응답 수신: %d자 token_usage=%s", len(content), token_usage)
    logger.debug("LLM 응답 원문(앞 500자): %s", content[:500])
    return LLMResult(content=content, model=actual_model, token_usage=token_usage)


def ask_with_usage(prompt: str, model: str | None = None) -> LLMResult:
    """user 프롬프트를 보내 답변과 토큰 사용량을 함께 받는다."""
    return chat_with_usage([{"role": "user", "content": prompt}], model=model)
