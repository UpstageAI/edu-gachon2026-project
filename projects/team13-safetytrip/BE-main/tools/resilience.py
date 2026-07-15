"""
Tool(DB/외부 API) 호출용 공용 재시도 유틸.
app/llm_client.py의 LLM 3단 방어(timeout/재시도/강등)와 같은 사상을,
stats_tool/retrieve_tool처럼 LLM이 아닌 도구 호출에도 적용하기 위함.

사용처: tools/stats_tool.py (Supabase DB 쿼리), tools/retrieve_tool.py (Solar Embedding API + DB 쿼리)
"""
import time
import logging

logger = logging.getLogger("tools.resilience")

MAX_RETRIES = 2
BACKOFF_BASE_SECONDS = 1  # 1초 -> 2초로 지수 증가


class ToolUnavailableError(Exception):
    """도구 호출이 재시도까지 다 실패한 경우. 호출부(그래프 노드)가 잡아서 우아하게 강등 처리해야 함."""
    pass


def call_with_retry(fn, *args, retryable_exceptions=(Exception,), max_retries=MAX_RETRIES, tool_name="tool", **kwargs):
    """
    fn(*args, **kwargs)을 실행하고, retryable_exceptions에 해당하는 예외가 나면
    지수 백오프로 재시도. 재시도까지 다 실패하면 ToolUnavailableError로 통일해서 던짐
    (호출부가 어떤 하위 라이브러리 예외인지 몰라도 되게).
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except retryable_exceptions as e:
            last_exc = e
            if attempt < max_retries:
                wait = BACKOFF_BASE_SECONDS * (2 ** attempt)
                logger.warning(
                    f"[{tool_name}] 호출 실패(시도 {attempt + 1}/{max_retries + 1}): {e}. {wait}초 후 재시도."
                )
                time.sleep(wait)
            else:
                logger.error(f"[{tool_name}] 호출 최종 실패 ({max_retries + 1}회 시도 소진): {e}")

    raise ToolUnavailableError(f"{tool_name}: {last_exc}") from last_exc