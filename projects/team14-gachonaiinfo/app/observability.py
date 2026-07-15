"""Langfuse 관측성 helper (LangGraph trace).

LangGraph 실행(router → rag/tool/reminder → response)을 Langfuse trace로 남겨
"왜 이렇게 라우팅됐는지 / RAG top_score·guardrail이 무엇인지"를 눈으로 볼 수 있게 한다.

설계 원칙
- config로 완전히 껐다 켤 수 있어야 한다: key가 없거나 LANGFUSE_ENABLED=false면
  Langfuse 관련 코드가 아무것도 실행되지 않는다(콜백 미주입, no-op context).
- 개인정보(이메일/전화)는 trace 전송 전에 마스킹한다: 리마인드 기능 때문에 이메일이
  input/output에 섞여 들어오므로, Langfuse 클라이언트의 mask 훅으로 일괄 치환한다.
- SDK는 v4(4.x) 기준. get_client()가 반환하는 전역 싱글톤을 우리가 먼저 mask와 함께
  구성해두면, langchain CallbackHandler도 같은 싱글톤을 사용한다.
"""

import re
from contextlib import nullcontext
from functools import lru_cache
from typing import Any

from app import config

# 마스킹 패턴: 이메일 + 국내 전화번호(하이픈/공백 구분, 02·0xx 지역번호·010 등).
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\b0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}\b")


def _mask_text(text: str) -> str:
    text = _EMAIL_RE.sub("[REDACTED EMAIL]", text)
    text = _PHONE_RE.sub("[REDACTED PHONE]", text)
    return text


def _mask(*, data: Any) -> Any:
    """Langfuse가 각 observation의 input/output/metadata에 대해 호출하는 마스킹 훅.

    data는 문자열/딕셔너리/리스트 등 임의 구조라 재귀적으로 훑어 문자열만 치환한다.
    (호출 규약은 langfuse가 mask(data=...) 키워드로 부른다.)
    """
    if isinstance(data, str):
        return _mask_text(data)
    if isinstance(data, dict):
        return {k: _mask(data=v) for k, v in data.items()}
    if isinstance(data, list | tuple):
        return type(data)(_mask(data=v) for v in data)
    return data


def is_langfuse_enabled() -> bool:
    return bool(
        config.LANGFUSE_ENABLED and config.LANGFUSE_PUBLIC_KEY and config.LANGFUSE_SECRET_KEY
    )


@lru_cache(maxsize=1)
def _init_client():
    """mask가 걸린 전역 Langfuse 싱글톤을 1회 생성. 이후 get_client()/CallbackHandler가 재사용."""
    from langfuse import Langfuse

    return Langfuse(
        public_key=config.LANGFUSE_PUBLIC_KEY,
        secret_key=config.LANGFUSE_SECRET_KEY,
        base_url=config.LANGFUSE_BASE_URL,
        environment=config.LANGFUSE_ENV,
        mask=_mask,
    )


@lru_cache(maxsize=1)
def _get_handler():
    """langchain CallbackHandler 싱글톤. 비활성 시 None."""
    if not is_langfuse_enabled():
        return None
    _init_client()  # mask 걸린 싱글톤을 먼저 구성해둔다
    from langfuse.langchain import CallbackHandler

    return CallbackHandler()


def build_run_config(thread_id: str, run_name: str) -> dict[str, Any]:
    """LangGraph 실행 config. Langfuse가 켜져 있으면 콜백을 주입한다."""
    run_config: dict[str, Any] = {
        "configurable": {"thread_id": thread_id},
        "run_name": run_name,
    }
    handler = _get_handler()
    if handler is not None:
        run_config["callbacks"] = [handler]
    return run_config


def trace_context(*, trace_name: str, session_id: str, tags: list[str], metadata: dict[str, Any]):
    """trace 이름/세션/태그/메타데이터를 이 블록 안의 모든 observation에 전파.

    비활성 시 아무것도 하지 않는 nullcontext를 반환하므로 호출부는 분기 없이 감싸면 된다.
    """
    if not is_langfuse_enabled():
        return nullcontext()

    from langfuse import propagate_attributes

    return propagate_attributes(
        trace_name=trace_name,
        session_id=session_id,
        tags=tags,
        metadata=metadata,
        environment=config.LANGFUSE_ENV,
    )


def record_rag_observation(
    *, question: str, categories: list[str] | None, k: int, docs: list[dict]
) -> None:
    """RAG 검색 결과(top_score/source/guardrail 판단 근거)를 trace에 span으로 남긴다.

    LangGraph 콜백만으로는 LLM 호출·노드 흐름은 보이지만 검색 점수/출처는 안 보인다.
    현재 활성 trace가 있으면 그 하위에 span으로 붙고, 없으면 조용히 무시된다.
    """
    if not is_langfuse_enabled():
        return
    try:
        from langfuse import get_client

        # mask가 걸린 싱글톤을 반드시 먼저 구성해둔다(호출 순서와 무관하게 마스킹 보장).
        _init_client()
        client = get_client()
        top_score = docs[0]["score"] if docs else 0.0
        with client.start_as_current_observation(as_type="span", name="rag.retrieve") as span:
            span.update(
                input={"question": question, "categories": categories, "k": k},
                output={
                    "doc_count": len(docs),
                    "top_score": top_score,
                    "guardrail": (not docs) or top_score < config.GUARDRAIL_MIN_SCORE,
                    "sources": [
                        {
                            "source": d.get("source"),
                            "page": d.get("page"),
                            "score": d.get("score"),
                            "category_l1": d.get("category_l1"),
                        }
                        for d in docs[:5]
                    ],
                },
            )
    except Exception:
        # 관측성은 부가기능이므로 실패해도 본 응답 흐름을 절대 막지 않는다.
        pass
