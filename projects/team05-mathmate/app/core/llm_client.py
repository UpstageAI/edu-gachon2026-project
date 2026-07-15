"""
Solar LLM 클라이언트 (LiteLLM 게이트웨이).
- 키가 없으면 호출하지 않고 None 반환 → 호출부가 Mock 규칙으로 폴백.
- 타임아웃·Retry·Fallback 내장, JSON이 아닌 응답도 최대한 복구.
- Langfuse 키가 있으면 모든 호출(프롬프트·응답·지연시간·에러)이 자동으로 트레이싱된다.
Day5: 여기 앞단에 LiteLLM 요청 가드레일(입력 필터)을 추가할 수 있음.
"""
import json
import logging
import re
from app.core import config

log = logging.getLogger(__name__)

_langfuse_configured = False


def is_enabled() -> bool:
    return config.USE_LLM


def _ensure_langfuse_callback() -> None:
    """Langfuse 키가 있으면 LiteLLM에 트레이싱 콜백을 한 번만 등록한다."""
    global _langfuse_configured
    if _langfuse_configured or not config.LANGFUSE_ENABLED:
        return
    import litellm

    litellm.success_callback = ["langfuse"]
    litellm.failure_callback = ["langfuse"]   # 실패한 호출도 트레이스에 남긴다
    _langfuse_configured = True


def _call(system: str, user: str, temperature: float, json_mode: bool, trace_name: str,
          trace_id: str | None = None):
    """LiteLLM으로 Solar 호출. 실패 시 예외를 그대로 올린다(상위에서 처리)."""
    import litellm  # 지연 임포트: 키 없는 환경/테스트에선 불필요

    _ensure_langfuse_callback()

    metadata = {"trace_name": trace_name}   # Langfuse 대시보드에서 호출 종류 구분용
    if trace_id:
        # eval 스크립트가 채점 결과를 langfuse.score(trace_id=...)로 이 트레이스에 붙일 수 있게
        # 트레이스 ID를 우리가 직접 지정한다(안 넘기면 LiteLLM이 임의로 생성).
        metadata["trace_id"] = trace_id

    kwargs = dict(
        model=f"openai/{config.SOLAR_MODEL}",
        api_base=config.SOLAR_BASE_URL,
        api_key=config.SOLAR_API_KEY,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
        timeout=config.LLM_TIMEOUT,
        num_retries=config.LLM_NUM_RETRIES,   # 429·5xx·타임아웃 자동 재시도(지수 백오프)
        metadata=metadata,
    )
    if config.FALLBACK_MODEL:
        # 문자열로만 넘기면 LiteLLM이 Solar용 api_key/api_base를 그대로 재사용해서
        # 대체 모델(예: Gemini) 호출이 무조건 실패한다 — 딕셔너리로 명시적으로 덮어써야 한다.
        kwargs["fallbacks"] = [{
            "model": config.FALLBACK_MODEL,
            "api_key": config.GEMINI_API_KEY,
            "api_base": None,
        }]
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = litellm.completion(**kwargs)
    return resp.choices[0].message.content


def chat_json(system: str, user: str, trace_name: str = "chat_json",
              trace_id: str | None = None) -> dict | None:
    """구조화(JSON) 응답을 dict로 반환. 비활성/실패/파싱불가 시 None."""
    if not config.USE_LLM:
        return None
    try:
        content = _call(system, user, temperature=0.0, json_mode=True, trace_name=trace_name,
                         trace_id=trace_id)
        return _safe_json(content)
    except Exception as e:   # 인증(401)·잘못된요청(400)·서버오류(5xx)·타임아웃 등
        _log_failure("JSON", e)
        return None


def chat_text(system: str, user: str, trace_name: str = "chat_text",
              trace_id: str | None = None) -> str | None:
    """자유 텍스트 응답. 비활성/실패 시 None."""
    if not config.USE_LLM:
        return None
    try:
        return _call(system, user, temperature=0.4, json_mode=False, trace_name=trace_name,
                      trace_id=trace_id)
    except Exception as e:
        _log_failure("텍스트", e)
        return None


def _log_failure(context: str, e: Exception) -> None:
    """에러 유형별로 원인을 구분해 로그를 남긴다. 폴백 동작(Mock)은 어떤 경우든 동일하다.

    - 인증 오류: 재시도해도 소용없음(키 문제) → 즉시 폴백
    - 요청 한도: num_retries만큼 이미 재시도한 뒤에도 실패한 것
    - 타임아웃/연결·서버 오류: 일시적 장애 가능성, 다음 요청에서 복구될 수 있음
    """
    import litellm.exceptions as exc   # 지연 임포트: 키 없는 환경/테스트에선 불필요

    if isinstance(e, exc.AuthenticationError):
        log.warning("Solar %s 호출 실패(인증 오류 — API 키 확인 필요) → Mock 폴백: %s", context, e)
    elif isinstance(e, exc.RateLimitError):
        log.warning("Solar %s 호출 실패(요청 한도 초과 — 재시도 모두 소진) → Mock 폴백: %s", context, e)
    elif isinstance(e, exc.Timeout):
        log.warning("Solar %s 호출 실패(응답 시간 초과) → Mock 폴백: %s", context, e)
    elif isinstance(e, (exc.APIConnectionError, exc.ServiceUnavailableError,
                         exc.InternalServerError, exc.BadGatewayError)):
        log.warning("Solar %s 호출 실패(서버/네트워크 오류) → Mock 폴백: %s", context, e)
    else:
        log.warning("Solar %s 호출 실패(알 수 없는 오류) → Mock 폴백: %s", context, e)


def _safe_json(text: str | None):
    """모델이 JSON이 아닌 잡텍스트(코드블록 등)를 섞어 줘도 최대한 복구."""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)   # 본문 속 첫 JSON 객체 추출
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                return None
    return None
