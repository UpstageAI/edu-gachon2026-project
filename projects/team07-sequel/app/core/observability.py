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


_NODES = {"normalize", "schema_link", "route", "generate", "validate", "execute", "format"}
_graph_handler = None


def _short(v, n: int = 800) -> str:
    s = str(v)
    return s if len(s) <= n else s[:n] + "…"


class _GraphTracer:
    """LangGraph → Langfuse: 질의 1건 = 트레이스 1개 + 노드별 span.

    langfuse 2.x 내장 langchain 핸들러는 langchain 0.x 전용(우리는 core 1.x)이라
    langchain_core 콜백 인터페이스(on_chain_start/end/error 덕타이핑)로 직접 매핑한다.
    litellm 콜백(LLM 낱개 로깅)과 상호 보완.
    """

    raise_error = False  # 트레이싱 실패가 파이프라인을 죽이지 않게 (langchain_core 규약)
    ignore_llm = ignore_retriever = ignore_agent = ignore_chat_model = True
    run_inline = True

    def __init__(self) -> None:
        from langfuse import Langfuse
        self._lf = Langfuse(public_key=settings.langfuse_public_key,
                            secret_key=settings.langfuse_secret_key,
                            host=settings.langfuse_host)
        self._root: dict = {}   # run_id -> 소속 루트 trace
        self._span: dict = {}   # run_id -> 열린 span/trace

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, name=None, **kw):
        n = name or (serialized or {}).get("name", "")
        if parent_run_id is None:                      # 그래프 루트 → 트레이스
            t = self._lf.trace(name="sequel-query", input=_short((inputs or {}).get("question", inputs)))
            self._root[run_id] = t
            self._span[run_id] = t
            return
        root = self._root.get(parent_run_id)
        if root is not None:
            self._root[run_id] = root                  # 중간 러너 통과해도 루트 계승
            if n in _NODES:                            # 우리 노드만 span 으로
                self._span[run_id] = root.span(name=n, input=_short(inputs))

    def _finish(self, run_id, **fields):
        obj = self._span.pop(run_id, None)
        self._root.pop(run_id, None)
        if obj is not None:
            (obj.end if hasattr(obj, "end") else obj.update)(**fields)

    def on_chain_end(self, outputs, *, run_id, **kw):
        self._finish(run_id, output=_short(outputs))

    def on_chain_error(self, error, *, run_id, **kw):
        self._finish(run_id, level="ERROR", status_message=_short(error, 300))

    def flush(self) -> None:
        self._lf.flush()


def graph_callbacks() -> list:
    """graph.ainvoke(config={'callbacks': ...}) 에 전달. 싱글턴, 키 없으면 [] (no-op)."""
    global _graph_handler
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return []
    if _graph_handler is None:
        from langchain_core.callbacks import BaseCallbackHandler

        _graph_handler = type("GraphTracer", (_GraphTracer, BaseCallbackHandler), {})()
    return [_graph_handler]


@contextmanager
def trace(name: str, **meta):
    """노드 실행 구간 표시(옵션). LLM 호출 자체는 litellm 콜백이 이미 로깅하므로 no-op.

    ponytail: 요청 단위 그룹핑(trace_id/session)이 필요해지면 여기서 metadata 를 붙인다.
    """
    yield None
