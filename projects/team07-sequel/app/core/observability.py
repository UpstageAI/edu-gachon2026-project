"""Langfuse 관측 — 트레이싱·비용/품질 로깅의 단일 지점.

litellm 네이티브 콜백을 켜면 core.llm.complete() 의 모든 호출이 자동으로
Langfuse 에 남는다(모델·프롬프트/응답·토큰·비용·지연). 별도 span 배선 불필요.
키가 없으면 no-op (로컬/CI 에서 조용히 비활성).

입력: settings.langfuse_* / 출력: None
"""
from __future__ import annotations

import json
import logging
import os
import re
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

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


# PII 규칙 마스킹 — B2B 로그가 Langfuse(제3자)로 나가기 전 기계적으로 가린다.
# 고정밀 패턴만(이메일·휴대폰·주민번호·카드) — 결과 행의 일반 숫자를 오탐하지 않게.
# 순서 주의: 주민번호(13자리) 를 카드(\d{13,19}) 보다 먼저 처리.
# ponytail: 이 목록이 튜닝 노브다. 계좌·여권 등 필요해지면 여기만 추가.
_PII = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"\b01[016-9][-.\s]?\d{3,4}[-.\s]?\d{4}\b"), "[PHONE]"),
    (re.compile(r"\b\d{6}[-\s]?[1-8]\d{6}\b"), "[RRN]"),           # 주민/외국인등록번호(7번째 자리 1~8)
    (re.compile(r"\b\d{13,19}\b"), "[CARD]"),                      # 붙은 카드/계좌번호
    (re.compile(r"\b(?:\d{4}[-\s]){3}\d{4}\b"), "[CARD]"),         # 4-4-4-4
]


def mask_pii(data):
    """로그로 나가기 전 PII 를 규칙으로 가린다. **절대 raise 하지 않는다**.

    litellm 의 langfuse 마스킹은 예외 시 원본을 그대로 로깅(fail-open)하므로,
    여기서 예외를 삼키고 삭제 표시를 돌려 **fail-closed**(유출 < 로그손실)를 강제한다.
    문자열은 규칙 치환, dict/list 는 재귀(중첩 값 속 PII 도 가림), 그 외(숫자 등)는 그대로 통과.
    langfuse 는 mask(data=...), litellm 은 mask(data) 로 부른다 → 단일 시그니처로 둘 다 커버.
    """
    try:
        if isinstance(data, str):
            for pat, repl in _PII:
                data = pat.sub(repl, data)
            return data
        if isinstance(data, dict):
            return {k: mask_pii(v) for k, v in data.items()}
        if isinstance(data, list):
            return [mask_pii(v) for v in data]
        if isinstance(data, tuple):
            return tuple(mask_pii(v) for v in data)
        return data
    except Exception:  # noqa: BLE001 — 못 가리면 원문 대신 삭제
        return "[MASK-ERROR]"


# 로컬 트레이스 로그 — Langfuse 가 드롭/실패해도 안 잃을 durable 사본(질의 1줄 = JSON).
# Langfuse 전송은 백그라운드 배치라 서버 다운·타임아웃·큐 풀 시 조용히 드롭된다.
# 그 순간을 감지하는 건 SDK 내부라 취약 → 매 질의를 로컬에 항상 남겨 감지 없이 커버한다.
_TRACE_LOG = Path(__file__).resolve().parents[2] / "logs" / "traces.jsonl"
_trace_logger = logging.getLogger("sequel.trace")


def log_trace_local(question, output=None, error=None) -> None:
    """질의 1건을 로컬 파일에 durable 기록 — Langfuse 성공/실패와 무관. 절대 raise 안 함.

    RotatingFileHandler 로 50MB(10MB×5) 상한 → 보관비용 자동 통제.
    내용은 mask_pii 로 가려 로컬 디스크에도 원문 PII 를 안 남긴다.
    """
    try:
        if not _trace_logger.handlers:
            _trace_logger.setLevel(logging.INFO)
            _trace_logger.propagate = False
            _TRACE_LOG.parent.mkdir(parents=True, exist_ok=True)
            h = RotatingFileHandler(_TRACE_LOG, maxBytes=10_000_000, backupCount=5, encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            _trace_logger.addHandler(h)
        rec = {"question": mask_pii(_short(question))}
        if error is not None:
            rec["level"] = "ERROR"
            rec["error"] = mask_pii(_short(error, 300))
        else:
            rec["output"] = mask_pii(_short(output))
        _trace_logger.info(json.dumps(rec, ensure_ascii=False))
    except Exception:  # noqa: BLE001 — 로컬 로깅 실패도 파이프라인 안 죽임
        pass


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
                            host=settings.langfuse_host,
                            mask=mask_pii)  # 노드 span input/output PII 마스킹 (SDK가 fail-closed)
        self._root: dict = {}   # run_id -> 소속 루트 trace
        self._span: dict = {}   # run_id -> 열린 span/trace
        self._q: dict = {}      # root run_id -> 질문 (로컬 로그 1줄/질의 용)

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, name=None, **kw):
        n = name or (serialized or {}).get("name", "")
        if parent_run_id is None:                      # 그래프 루트 → 트레이스
            t = self._lf.trace(name="sequel-query", input=_short((inputs or {}).get("question", inputs)))
            self._root[run_id] = t
            self._span[run_id] = t
            self._q[run_id] = (inputs or {}).get("question", inputs)
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
        if run_id in self._q:                          # 루트 종료 = 질의 1건 완료 → 로컬 durable 기록
            log_trace_local(self._q.pop(run_id), output=outputs)

    def on_chain_error(self, error, *, run_id, **kw):
        self._finish(run_id, level="ERROR", status_message=_short(error, 300))
        if run_id in self._q:
            log_trace_local(self._q.pop(run_id), error=error)

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
