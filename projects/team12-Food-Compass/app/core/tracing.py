"""Langfuse 트레이싱 초기화 (LLMOps 선택 가점 항목).

langfuse/langchain 패키지는 pyproject.toml의 "stretch"(선택) 의존성 그룹에 있어
CI(`uv sync --frozen --group dev`)와 이 그룹을 설치하지 않은 팀원 환경에는 없을 수 있다.
이 모듈은 패키지가 없거나 LANGFUSE_* 값이 비어있어도 절대 예외를 던지지 않고 조용히
트레이싱을 건너뛴다 — get_trace_callbacks()가 항상 빈 리스트를 반환하면
`compiled_graph.astream(..., config={"callbacks": get_trace_callbacks()})`는
콜백이 하나도 없는 것과 동일하게 동작해 기존 흐름에 아무 영향이 없다.
"""
from __future__ import annotations

from typing import Any

from app.core.config import settings

_callback_handler: Any = None

if settings.langfuse_tracing_enabled and settings.langfuse_public_key and settings.langfuse_secret_key:
    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler

        # get_client()가 아니라 여기서 직접 Langfuse(...)를 생성하는 이유: get_client()는
        # 프로세스 환경변수(os.environ)에서 키를 읽는데, load_dotenv() 호출 순서가 모듈마다
        # 제각각이라(app/tools/*.py 각자 load_dotenv() 호출) import 타이밍에 따라 os.environ이
        # 아직 안 채워졌을 수 있음 — 우리 pydantic Settings(.env를 자체적으로 읽음)의 값을
        # 명시적으로 넘겨서 이 타이밍 문제를 원천적으로 피한다.
        # 같은 public_key로 Langfuse()를 다시 호출해도 SDK가 기존 싱글턴을 재사용하므로
        # 아래 CallbackHandler()는 항상 이 인스턴스(base_url 포함)를 사용하게 된다.
        Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url or None,
        )
        _callback_handler = CallbackHandler()
        print("[tracing] Langfuse 트레이싱 활성화됨")
    except ImportError:
        # "stretch" 그룹 미설치 — 정상적인 상태(선택 가점 항목이라 필수 아님)
        print("[tracing] langfuse 패키지 미설치 — 트레이싱 없이 계속 진행 (uv sync --group stretch로 설치 가능)")
    except Exception as e:
        # 키 오타, 네트워크 문제 등 — 트레이싱 실패가 실제 서비스 응답까지 막으면 안 됨
        print(f"[tracing] Langfuse 초기화 실패, 트레이싱 없이 계속 진행: {e!r}")


def get_trace_callbacks() -> list[Any]:
    """LangGraph astream/ainvoke의 config={"callbacks": ...}에 그대로 넣을 콜백 목록."""
    return [_callback_handler] if _callback_handler is not None else []


def flush_traces() -> None:
    """프로세스 종료(서버 shutdown, CLI 종료) 시 배치로 쌓인 트레이스를 마저 전송 — 실패해도 종료를 막지 않음."""
    if _callback_handler is None:
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception as e:
        print(f"[tracing] flush 실패(무시): {e!r}")
