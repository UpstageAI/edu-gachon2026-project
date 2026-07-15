"""LLM 인스턴스 생성 + 주/백업 모델 폴백 (LLMOps 안정성).

주 모델(settings.llm_model, 예: solar-pro3) 호출이 실패하면(모델 장애·일시적 오류 등)
백업 모델(settings.llm_fallback_model)로 한 번 더 시도한다. LiteLLM 같은 별도
게이트웨이/의존성 없이 코드로 직접 처리 — "주 모델이 안 될 때 대비 모델 하나만 두고
싶다"는 요구에 맞춘 최소 구현.

router.py(구조화 출력, async)와 nodes.py(일반 답변, sync)가 공용으로 쓰도록 여기 모음
— 기존엔 두 파일에 _get_llm()이 각각 중복돼 있었음.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage
from langchain_upstage import ChatUpstage
from pydantic import BaseModel

from app.core.config import settings


def build_llm(model: str) -> ChatUpstage:
    return ChatUpstage(
        api_key=settings.upstage_api_key,
        model=model,
        timeout=30,
        max_retries=2,
    )


_primary = build_llm(settings.llm_model)
_fallback = build_llm(settings.llm_fallback_model) if settings.llm_fallback_model else None


def invoke_with_fallback(messages: list[BaseMessage]) -> Any:
    """주 모델로 invoke, 실패하면 백업 모델로 재시도. 둘 다 실패하면 예외를 그대로 올림."""
    try:
        return _primary.invoke(messages)
    except Exception as e:
        if _fallback is None:
            raise
        print(f"[llm] 주 모델({settings.llm_model}) 호출 실패 → 백업 모델({settings.llm_fallback_model})로 재시도: {e!r}")
        return _fallback.invoke(messages)


async def ainvoke_structured_with_fallback(schema: type[BaseModel], messages: list[BaseMessage]) -> Any:
    """구조화 출력(with_structured_output) async 버전 — 주 모델 실패 시 백업 모델로 재시도."""
    try:
        return await _primary.with_structured_output(schema).ainvoke(messages)
    except Exception as e:
        if _fallback is None:
            raise
        print(f"[llm] 주 모델({settings.llm_model}) 구조화 호출 실패 → 백업 모델({settings.llm_fallback_model})로 재시도: {e!r}")
        return await _fallback.with_structured_output(schema).ainvoke(messages)
