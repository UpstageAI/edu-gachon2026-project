"""Langfuse 관측 — 트레이싱·비용/품질 로깅의 단일 지점.

litellm 네이티브 콜백을 켜면 core.llm.complete() 의 모든 호출이 자동으로
Langfuse 에 남는다(모델·프롬프트/응답·토큰·비용·지연). 별도 span 배선 불필요.
키가 없으면 no-op (로컬/CI 에서 조용히 비활성).

입력: settings.langfuse_* / 출력: None
"""
from __future__ import annotations

import os
from contextlib import contextmanager

import litellm

from app.core.settings import settings

_enabled = False


def init_observability() -> None:
    """앱 시작 시 Langfuse 콜백 등록. 키 없으면 no-op."""
    global _enabled
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
    os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
    os.environ["LANGFUSE_HOST"] = settings.langfuse_host
    litellm.success_callback = ["langfuse"]
    litellm.failure_callback = ["langfuse"]
    _enabled = True


@contextmanager
def trace(name: str, **meta):
    """노드 실행 구간 표시(옵션). LLM 호출 자체는 litellm 콜백이 이미 로깅하므로 no-op.

    ponytail: 요청 단위 그룹핑(trace_id/session)이 필요해지면 여기서 metadata 를 붙인다.
    """
    yield None
