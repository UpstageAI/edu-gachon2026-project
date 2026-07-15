from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from functools import lru_cache
from types import TracebackType
from typing import Any

from langfuse import Langfuse, propagate_attributes
from langfuse.langchain import CallbackHandler

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class _NoopTraceContext(AbstractContextManager[None]):
    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


@lru_cache
def get_langfuse_client() -> Langfuse | None:
    """Initialize one Langfuse client when both project keys are configured."""

    settings = get_settings()
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return None

    try:
        return Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url,
            environment=settings.langfuse_tracing_environment,
        )
    except Exception:  # noqa: BLE001 - observability must not stop the chat API
        logger.warning("Langfuse 클라이언트 초기화에 실패해 tracing을 비활성화합니다.")
        return None


def create_langfuse_handler(*, trace_id: str | None = None) -> CallbackHandler | None:
    """Create an isolated callback handler for one graph invocation.

    trace_id를 미리 지정하면(예: 사용자 피드백을 나중에 이 트레이스에 연결하기 위해)
    호출자가 그 값을 그대로 기억해 쓸 수 있다. 그래프 실행이 끝나면 콜백이 만든
    span의 컨텍스트가 이미 닫혀 있어 사후에 get_current_trace_id()로는 못 가져온다.
    """

    if get_langfuse_client() is None:
        return None

    try:
        trace_context = {"trace_id": trace_id} if trace_id else None
        return CallbackHandler(public_key=get_settings().langfuse_public_key, trace_context=trace_context)
    except Exception:  # noqa: BLE001 - tracing is optional
        logger.warning("Langfuse callback 생성에 실패해 현재 요청의 tracing을 건너뜁니다.")
        return None


def langfuse_trace_context(session_id: str, *, enabled: bool) -> AbstractContextManager[Any]:
    """Attach searchable trace attributes without treating a session as a user identity."""

    if not enabled:
        return _NoopTraceContext()

    return propagate_attributes(
        trace_name="Policy Compass Chat",
        session_id=session_id,
        tags=["langgraph", "policy-compass"],
        metadata={"framework": "langgraph", "service": "policy-compass"},
    )


def shutdown_langfuse() -> None:
    """Flush pending observations during application shutdown."""

    client = get_langfuse_client()
    if client is None:
        return

    try:
        client.shutdown()
    except Exception:  # noqa: BLE001 - shutdown telemetry must not block app shutdown
        logger.warning("Langfuse trace flush를 완료하지 못했습니다.")
