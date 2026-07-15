import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

from loguru import logger

from app.core.config import settings
from app.core.observability import start_observation, summarize_messages


DEFAULT_SYSTEM_PROMPT = "너는 법제처 생활법령 백문백답 기반 생활법률 안내 챗봇이다."
UPSTAGE_API_BASE = "https://api.upstage.ai/v1"

# 대체 모델 (팀 확정 2026-07-14): 메인 모델 2회 실패 시 1회 시도한다.
# Upstage /v1/models 실측으로 존재를 확인한 alias id. 메인(solar-pro3)과 같은 alias 형식.
# 스냅샷 고정이 필요해지면 solar-pro2-251215로 교체한다.
FALLBACK_MODEL = "solar-pro2"
RETRY_WAIT_SECONDS = 1.0  # 메인 모델 재시도 전 대기 시간
# 체인(메인→재시도→대체) 전부 실패 시 사용자에게 보여줄 고정 문구 (단일 정의).
# sync는 nodes.generate가, stream은 chat.py의 error 이벤트가 이 메시지를 사용한다.
LLM_FAILURE_MESSAGE = "일시적 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."


class LLMError(Exception):
    """LLM 호출 실패를 상위 계층에서 공통으로 처리하기 위한 예외."""


def generate_text(prompt: str, system: Optional[str] = None) -> str:
    """Upstage Solar 응답을 문자열로 반환한다."""
    messages = _build_messages(prompt=prompt, system=system)

    with start_observation(
        name="generation",
        as_type="generation",
        input={"messages": summarize_messages(messages)},
        metadata={"provider": "upstage", "stream": False},
        model=settings.llm_model,
        model_parameters={"stream": False},
    ) as observation:
        try:
            response, used_model, retry_count = _completion_with_retry(
                messages=messages,
                stream=False,
            )
            content = _extract_message_content(response)
        except LLMError as exc:
            observation.update(level="ERROR", status_message=_failure_status(exc))
            raise
        except Exception as exc:
            observation.update(level="ERROR", status_message=type(exc).__name__)
            raise LLMError("LLM text generation failed.") from exc

        if not content:
            observation.update(level="ERROR", status_message="empty_response")
            raise LLMError("LLM returned an empty response.")

        observation.update(
            output=content,
            usage_details=_extract_usage_details(response),
            model=used_model,  # 대체 모델로 응답한 경우 실제 사용 모델을 기록한다
            metadata=_retry_metadata(used_model, retry_count),
        )
        return content


def stream_text(prompt: str, system: Optional[str] = None) -> Iterator[str]:
    """Upstage Solar 응답 조각을 순차적으로 반환한다."""
    messages = _build_messages(prompt=prompt, system=system)

    with start_observation(
        name="generation",
        as_type="generation",
        input={"messages": summarize_messages(messages)},
        metadata={"provider": "upstage", "stream": True},
        model=settings.llm_model,
        model_parameters={"stream": True},
    ) as observation:
        try:
            response, used_model, retry_count = _completion_with_retry(
                messages=messages,
                stream=True,
            )
        except LLMError as exc:
            observation.update(level="ERROR", status_message=_failure_status(exc))
            raise
        except Exception as exc:
            observation.update(level="ERROR", status_message=type(exc).__name__)
            raise LLMError("LLM text streaming failed.") from exc

        observation.update(
            model=used_model,  # 대체 모델로 응답한 경우 실제 사용 모델을 기록한다
            metadata=_retry_metadata(used_model, retry_count),
        )

        # 스트리밍 특칙: 아래 반복 중(토큰 일부 전송 후) 실패는 재시도·전환 없이
        # 즉시 오류 처리한다. 이미 클라이언트로 나간 토큰을 회수할 수 없어
        # 재시도하면 답변이 중복 출력되기 때문이다.
        try:
            chunks = []
            for chunk in response:
                text = _extract_stream_text(chunk)
                if text:
                    chunks.append(text)
                    yield text
            observation.update(output="".join(chunks))
        except Exception as exc:
            observation.update(level="ERROR", status_message=type(exc).__name__)
            raise LLMError("LLM text streaming failed.") from exc


def _completion_with_retry(messages: List[Dict[str, str]], stream: bool) -> Tuple[Any, str, int]:
    """메인 모델 → (1초 후) 메인 재시도 → 대체 모델 1회의 호출 체인.

    - 시도 목록이 3개로 고정되어 있어 총 호출이 구조적으로 3회를 넘지 않는다.
    - 재시도·전환 대상은 _retryable_exceptions()의 litellm 예외뿐이다.
      그 외 예외(TypeError 같은 코드 결함)는 첫 시도에서 즉시 전파된다.
    - generation observation은 호출자(generate_text/stream_text)가 1회만 만들므로
      재시도가 있어도 observation·trace가 중복 생성되지 않는다.
    - 반환: (응답, 실제 사용 모델 id, retry_count) — retry_count는 추가 시도 횟수
      (0=첫 시도 성공, 1=메인 재시도로 성공, 2=대체 모델로 성공).
    """
    retryable = _retryable_exceptions()
    attempt_models = (None, None, FALLBACK_MODEL)  # None = 메인 모델(settings.llm_model)
    last_error: Optional[Exception] = None

    for attempt, model_override in enumerate(attempt_models):
        try:
            if model_override is None:
                response = _completion(messages=messages, stream=stream)
            else:
                response = _completion(messages=messages, stream=stream, model=model_override)
        except retryable as exc:
            last_error = exc
            if attempt == 0:
                logger.warning(
                    "LLM 메인 모델 호출 실패({}) — {}초 후 재시도",
                    type(exc).__name__,
                    RETRY_WAIT_SECONDS,
                )
                time.sleep(RETRY_WAIT_SECONDS)
            elif attempt == 1:
                logger.warning(
                    "LLM 메인 모델 2회 실패({}) — 대체 모델로 전환: {}",
                    type(exc).__name__,
                    FALLBACK_MODEL,
                )
            else:
                logger.error(
                    "LLM 대체 모델까지 실패({}) — 고정 문구 fallback으로 응답",
                    type(exc).__name__,
                )
            continue

        used_model = model_override or settings.llm_model
        if model_override is not None:
            logger.warning("main model failed twice, answered with fallback model {}", used_model)
        return response, used_model, attempt

    raise LLMError(LLM_FAILURE_MESSAGE) from last_error


def _retryable_exceptions() -> tuple:
    """재시도·전환 대상 예외 — litellm의 API 호출 실패 계열로 명시적 한정.

    timeout / rate limit / 연결 오류 / 서버 오류(5xx) / API 오류(모델명 오류 등
    4xx 포함 — 대체 모델 전환으로 복구될 수 있음) / 인증 오류(재시도는 무의미하지만
    체인을 거쳐 최종 고정 문구 경로로 수렴). 광범위 Exception 재시도는 금지.
    """
    try:
        from litellm import exceptions as litellm_exceptions
    except ModuleNotFoundError:
        return ()

    return (
        litellm_exceptions.Timeout,
        litellm_exceptions.RateLimitError,
        litellm_exceptions.APIConnectionError,
        litellm_exceptions.InternalServerError,
        litellm_exceptions.ServiceUnavailableError,
        litellm_exceptions.APIError,
        litellm_exceptions.NotFoundError,
        litellm_exceptions.BadRequestError,
        litellm_exceptions.AuthenticationError,
    )


def _retry_metadata(used_model: str, retry_count: int) -> Dict[str, Any]:
    """재시도·전환 발생 사실을 generation observation metadata에 남긴다 (v4 정합성)."""
    return {
        "retry_count": retry_count,
        "used_fallback_model": used_model != settings.llm_model,
    }


def _failure_status(exc: LLMError) -> str:
    """관측용 status_message — 원인 예외 타입을 우선 기록한다."""
    cause = exc.__cause__
    return type(cause).__name__ if cause is not None else type(exc).__name__


def _completion(messages: List[Dict[str, str]], stream: bool, model: Optional[str] = None) -> Any:
    # model 인자는 하위호환용 optional — 기존 호출·테스트는 (messages, stream)만 넘긴다.
    if not settings.upstage_api_key:
        raise LLMError("UPSTAGE_API_KEY is not configured.")

    try:
        from litellm import completion
    except ModuleNotFoundError as exc:
        raise LLMError("litellm is not installed.") from exc

    return completion(
        model=_litellm_model_name(model or settings.llm_model),
        messages=messages,
        api_key=settings.upstage_api_key,
        api_base=UPSTAGE_API_BASE,
        stream=stream,
    )


def _build_messages(prompt: str, system: Optional[str]) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": system or DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]


def _litellm_model_name(model: str) -> str:
    if model.startswith("openai/"):
        return model
    if model.startswith("upstage/"):
        return f"openai/{model.split('/', 1)[1]}"
    return f"openai/{model}"


def _extract_message_content(response: Any) -> str:
    choice = response["choices"][0] if isinstance(response, dict) else response.choices[0]
    message = choice["message"] if isinstance(choice, dict) else choice.message
    content = message["content"] if isinstance(message, dict) else message.content
    return content.strip() if content else ""


def _extract_stream_text(chunk: Any) -> str:
    choice = chunk["choices"][0] if isinstance(chunk, dict) else chunk.choices[0]
    delta = choice["delta"] if isinstance(choice, dict) else choice.delta
    content = delta.get("content") if isinstance(delta, dict) else getattr(delta, "content", None)
    return content or ""


def _extract_usage_details(response: Any) -> Optional[dict[str, int]]:
    usage = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
    if not usage:
        return None

    usage_key_map = {
        "prompt_tokens": "input",
        "input_tokens": "input",
        "completion_tokens": "output",
        "output_tokens": "output",
        "total_tokens": "total",
    }
    usage_details = {}
    for source_key, target_key in usage_key_map.items():
        value = usage.get(source_key) if isinstance(usage, dict) else getattr(usage, source_key, None)
        if isinstance(value, int):
            usage_details[target_key] = value
    return usage_details or None


# TODO: Day3에서 call_with_retry() 기반 재시도 정책은 구현하지 않는다.
# TODO: Day3에서 classify_text() 기반 LLM 분류는 구현하지 않는다.
