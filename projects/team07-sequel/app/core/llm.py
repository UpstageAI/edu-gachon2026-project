"""LiteLLM 게이트웨이 — 모든 LLM 호출의 단일 진입점.

라우터가 고른 solar 모델로 chat completion 을 호출한다. 노드는 직접 litellm 을
부르지 않고 이 함수만 쓴다(토큰/비용/트레이스 단일화).

Upstage 는 OpenAI 호환이라 litellm 의 openai provider + api_base 로 호출한다
(solar-pro3 등 임의 모델 문자열도 그대로 통과).

입력: model(str, 예 "solar-mini"), messages(list[{"role","content"}]),
      temperature(float|None), max_tokens(int|None)
출력: LLMResult(text, prompt_tokens, completion_tokens, model)
"""
from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager
from dataclasses import dataclass

import litellm

from app.core.settings import settings

litellm.suppress_debug_info = True

# 직전 complete() 호출의 토큰 사용량 (스레드별) — 비용 계측용(예: route_eval).
_last = threading.local()

# 요청 1건 동안의 토큰 누적기. complete() 는 한 질의에서 여러 노드(normalize·route·
# generate·format)가 각각 호출하므로 last_usage("직전 1콜")로는 합계를 못 낸다.
# ContextVar 라 요청(async task)마다 격리되고, LangGraph 가 동기 노드를 executor
# 스레드로 돌려도 copy_context 로 같은 누적 dict 가 전파돼 in-place 합산이 보인다.
_usage_acc: contextvars.ContextVar[dict | None] = contextvars.ContextVar("usage_acc", default=None)


def last_usage() -> tuple[int, int]:
    """이 스레드에서 마지막 complete() 의 (prompt_tokens, completion_tokens)."""
    return getattr(_last, "usage", (0, 0))


@contextmanager
def collect_usage():
    """이 블록 안에서 일어난 모든 complete() 의 토큰을 합산한다.

    출력(yield): {"input": int, "output": int, "calls": int} — 블록 종료 후에도 값 유효.
    """
    acc = {"input": 0, "output": 0, "calls": 0}
    token = _usage_acc.set(acc)
    try:
        yield acc
    finally:
        try:
            _usage_acc.reset(token)
        except ValueError:  # async generator 등 컨텍스트가 갈린 경우 — 조용히 해제
            _usage_acc.set(None)


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""


def complete(
    model: str,
    messages: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> LLMResult:
    """Solar chat completion 1회 (Upstage OpenAI 호환)."""
    resp = litellm.completion(
        model=f"openai/{model}",
        messages=messages,
        api_base=settings.upstage_base_url,
        api_key=settings.upstage_api_key,
        temperature=settings.llm_temperature if temperature is None else temperature,
        max_tokens=settings.llm_max_tokens if max_tokens is None else max_tokens,
        num_retries=3,   # 레이트리밋/일시오류 지수 백오프 재시도 (Retry-After 준수)
        timeout=60,
    )
    usage = resp.usage
    ptok = getattr(usage, "prompt_tokens", 0)
    ctok = getattr(usage, "completion_tokens", 0)
    _last.usage = (ptok, ctok)
    acc = _usage_acc.get()
    if acc is not None:  # collect_usage() 블록 안이면 질의 단위로 합산
        acc["input"] += ptok
        acc["output"] += ctok
        acc["calls"] += 1
    return LLMResult(
        text=resp.choices[0].message.content or "",
        prompt_tokens=ptok,
        completion_tokens=ctok,
        model=model,
    )
