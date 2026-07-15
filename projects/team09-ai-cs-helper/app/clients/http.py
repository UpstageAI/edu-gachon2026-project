"""
LLM(LiteLLM) 호출과 Supabase REST 호출이 공통으로 사용.

일시적인 네트워크/서버 오류(연결 끊김, 타임아웃, 429, 5xx)는 지수 백오프로
자동 재시도해 외부 연결 에러가 곧바로 사용자 실패로 이어지지 않도록 한다.
"""

import http.client
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# 타임아웃(초): LLM 추론은 느리므로 넉넉히, Supabase REST 등 일반 호출은 짧게.
DEFAULT_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "15"))
LLM_TIMEOUT = float(os.getenv("HTTP_LLM_TIMEOUT", "120"))

# 재시도 설정. 마지막 시도까지 실패해야 RuntimeError를 낸다.
MAX_RETRIES = int(os.getenv("HTTP_MAX_RETRIES", "3"))
RETRY_BACKOFF = float(os.getenv("HTTP_RETRY_BACKOFF", "0.5"))
# 일시적이라 재시도할 가치가 있는 HTTP 상태코드(429 rate limit + 5xx 서버 오류).
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def env(name: str) -> str:
    """필수 환경변수를 읽는다. 값이 없으면 RuntimeError."""
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


class _RetryableError(Exception):
    """내부용: 재시도할 가치가 있는 일시적 실패를 표시한다."""


def _send(request: urllib.request.Request, timeout: float) -> Any:
    """요청을 한 번 보낸다. 일시적 오류는 _RetryableError로 변환해 올린다."""
    method = request.get_method()
    url = request.full_url
    logger.debug("HTTP %s %s", method, url)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            logger.debug("HTTP %s %s -> %s (%d bytes)", method, url, response.status, len(body))
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code in RETRYABLE_STATUS:
            # 429/5xx는 잠시 후 회복될 수 있으므로 재시도 대상으로 올린다.
            raise _RetryableError(f"HTTP {exc.code}: {detail}") from exc
        logger.error("HTTP %s %s -> %d: %s", method, url, exc.code, detail)
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except (
        http.client.RemoteDisconnected,
        urllib.error.URLError,
        TimeoutError,  # urlopen 읽기 타임아웃(socket.timeout)은 URLError로 안 잡힘
        ConnectionError,
    ) as exc:
        raise _RetryableError(f"Connection failed: {exc}") from exc


def read_json(
    request: urllib.request.Request,
    timeout: float | None = None,
    retries: int = MAX_RETRIES,
) -> Any:
    """요청을 보내고 JSON 응답을 파싱한다. 일시적 실패는 지수 백오프로 재시도한다.

    주의: POST INSERT처럼 멱등하지 않은 요청은 첫 응답을 받기 전에 끊기면
    재시도로 중복 생성될 여지가 있다. 필요한 호출은 retries=1로 끌 수 있다.
    """
    method = request.get_method()
    url = request.full_url
    effective_timeout = DEFAULT_TIMEOUT if timeout is None else timeout
    last_reason = ""
    for attempt in range(1, retries + 1):
        try:
            return _send(request, effective_timeout)
        except _RetryableError as retryable:
            last_reason = str(retryable)
            if attempt >= retries:
                break
            wait = RETRY_BACKOFF * (2 ** (attempt - 1))  # 0.5s, 1s, 2s ...
            logger.warning(
                "HTTP %s %s -> 일시적 실패(%d/%d): %s (%.1fs 후 재시도)",
                method,
                url,
                attempt,
                retries,
                last_reason,
                wait,
            )
            time.sleep(wait)
    logger.error("HTTP %s %s -> %d회 시도 모두 실패: %s", method, url, retries, last_reason)
    raise RuntimeError(last_reason)


def post_json(
    url: str,
    headers: dict[str, str],
    payload: Any,
    timeout: float | None = None,
) -> Any:
    """POST 요청을 보내고 JSON 응답을 파싱한다."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    return read_json(request, timeout=timeout)
