import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Optional

from loguru import logger

from app.core.config import settings
from app.core.routing import EXACT_DISTANCE_THRESHOLD, RELATED_DISTANCE_THRESHOLD


MAX_TRACE_TEXT_LENGTH = 1200
MAX_METADATA_TEXT_LENGTH = 200
DEFAULT_TOP_K = 3

_LANGFUSE_CLIENT: Optional[Any] = None
_LANGFUSE_CLIENT_CONFIG: Optional[tuple[str, str, str, str]] = None
_LANGFUSE_IMPORT_WARNING_LOGGED = False
_LANGFUSE_CONFIG_WARNING_LOGGED = False

_SENSITIVE_PATTERNS = (
    (re.compile(r"\b\d{6}[-\s]?[1-4]\d{6}\b"), "[masked-resident-id]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[masked-email]"),
    (re.compile(r"\b(?:\+82[-\s]?)?0?1[016789][-\s]?\d{3,4}[-\s]?\d{4}\b"), "[masked-phone]"),
    (re.compile(r"\b\d{2,6}[-\s]\d{2,6}[-\s]\d{2,8}(?:[-\s]\d{1,4})?\b"), "[masked-account]"),
    (re.compile(r"\b\d{9,}\b"), "[masked-number]"),
)


@dataclass
class ObservationHandle:
    name: str
    observation: Optional[Any] = None

    @property
    def enabled(self) -> bool:
        return self.observation is not None

    def update(self, **kwargs: Any) -> None:
        if self.observation is None:
            return

        safe_kwargs = {
            key: sanitize_for_trace(value, limit=MAX_TRACE_TEXT_LENGTH)
            for key, value in kwargs.items()
            if value is not None
        }
        try:
            self.observation.update(**safe_kwargs)
        except Exception as exc:
            logger.warning("Langfuse observation update failed for {}: {}", self.name, exc)


def is_langfuse_configured() -> bool:
    return bool(
        settings.langfuse_enabled
        and settings.langfuse_public_key
        and settings.langfuse_secret_key
    )


def mask_sensitive_text(text: Any, limit: int = MAX_TRACE_TEXT_LENGTH) -> str:
    masked = str(text or "")
    for pattern, replacement in _SENSITIVE_PATTERNS:
        masked = pattern.sub(replacement, masked)
    return _truncate_text(masked, limit)


def sanitize_for_trace(value: Any, limit: int = MAX_TRACE_TEXT_LENGTH) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return mask_sensitive_text(value, limit=limit)
    if isinstance(value, dict):
        return {
            str(key): sanitize_for_trace(item, limit=limit)
            for key, item in value.items()
            if not _looks_sensitive_key(str(key))
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_for_trace(item, limit=limit) for item in value]
    return mask_sensitive_text(value, limit=limit)


def summarize_documents(documents: list[Any]) -> list[dict[str, Any]]:
    summaries = []
    for document in documents:
        summaries.append(
            {
                "id": getattr(document, "id", ""),
                "category": getattr(document, "category", ""),
                "question": mask_sensitive_text(
                    getattr(document, "question", ""), limit=MAX_METADATA_TEXT_LENGTH
                ),
            }
        )
    return summaries


def summarize_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "role": message.get("role", ""),
            "content": mask_sensitive_text(message.get("content", "")),
        }
        for message in messages
    ]


def build_trace_metadata(
    *,
    endpoint: str,
    mode: str,
    guardrail_result: str = "unknown",
    retrieved_count: int = 0,
    response_type: str = "pending",
    success: bool = True,
    error_type: Optional[str] = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "endpoint": endpoint,
        "mode": mode,
        "environment": settings.environment,
        "model": settings.llm_model,
        "guardrail_result": guardrail_result,
        "retrieved_count": retrieved_count,
        "response_type": response_type,
        "success": success,
    }
    if error_type:
        metadata["error_type"] = error_type
    return metadata


def build_route_trace_metadata(state: dict[str, Any]) -> dict[str, Any]:
    response_type = response_type_from_state(state)
    suggested_questions = state.get("suggested_questions") or []
    metadata = {
        "response_type": response_type,
        "guardrail_result": guardrail_result_from_state(state),
        "domain_category": state.get("domain_category"),
        "guardrail_reason": state.get("guardrail_reason"),
        "domain_keyword_hits": state.get("domain_keyword_hits", []),
        "extended_domain_hits": state.get("extended_domain_hits", []),
        "context_keyword_hits": state.get("context_keyword_hits", []),
        "out_of_scope_hits": state.get("out_of_scope_hits", []),
        "best_distance": state.get("best_distance"),
        "top1_distance": state.get("top1_distance"),
        "top2_distance": state.get("top2_distance"),
        "top3_distance": state.get("top3_distance"),
        "top1_document_id": state.get("top1_document_id"),
        "top2_document_id": state.get("top2_document_id"),
        "top3_document_id": state.get("top3_document_id"),
        "exact_threshold": EXACT_DISTANCE_THRESHOLD,
        "related_threshold": RELATED_DISTANCE_THRESHOLD,
        "retrieved_count": state.get("retrieved_count", 0),
        "exact_document_count": state.get("exact_document_count", 0),
        "related_document_count": state.get("related_document_count", 0),
        "grounded": state.get("is_grounded", False),
        "llm_general_knowledge_used": response_type in {"related_hybrid", "llm_only"},
        "suggestion_count": len(suggested_questions),
    }

    if "retry_used" in state:
        metadata["retry_used"] = state["retry_used"]
    if "model_fallback_used" in state:
        metadata["model_fallback_used"] = state["model_fallback_used"]

    return {key: value for key, value in metadata.items() if value is not None}


def response_type_from_state(state: dict[str, Any]) -> str:
    if state.get("response_type"):
        return str(state["response_type"])
    if state.get("guardrail_blocked"):
        return "blocked"
    if state.get("is_fallback"):
        return "no_result"
    return "normal"


def guardrail_result_from_state(state: dict[str, Any]) -> str:
    if state.get("domain_guardrail_result"):
        return str(state["domain_guardrail_result"])
    if state.get("guardrail_blocked"):
        return "blocked"
    if "guardrail_blocked" in state:
        return "allow"
    return "unknown"


def trace_tags(mode: str, response_type: str) -> list[str]:
    return [mode, response_type, settings.environment]


@contextmanager
def start_trace(
    *,
    name: str,
    input: Any,
    metadata: Optional[dict[str, Any]] = None,
    tags: Optional[list[str]] = None,
) -> Iterator[ObservationHandle]:
    trace_metadata = dict(metadata or {})
    if tags:
        trace_metadata["tags"] = tags

    with start_observation(
        name=name,
        as_type="span",
        input=input,
        metadata=trace_metadata,
    ) as observation:
        add_trace_attributes(trace_name=name, tags=tags)
        yield observation


@contextmanager
def start_observation(
    *,
    name: str,
    as_type: str = "span",
    input: Any = None,
    metadata: Optional[dict[str, Any]] = None,
    model: Optional[str] = None,
    model_parameters: Optional[dict[str, Any]] = None,
    usage_details: Optional[dict[str, int]] = None,
) -> Iterator[ObservationHandle]:
    client = _get_langfuse_client()
    if client is None:
        yield ObservationHandle(name=name)
        return

    kwargs: dict[str, Any] = {
        "name": name,
        "as_type": as_type,
    }
    if input is not None:
        kwargs["input"] = sanitize_for_trace(input)
    if metadata:
        kwargs["metadata"] = sanitize_for_trace(metadata)
    if model:
        kwargs["model"] = model
    if model_parameters:
        kwargs["model_parameters"] = sanitize_for_trace(model_parameters)
    if usage_details:
        kwargs["usage_details"] = usage_details

    manager = None
    try:
        manager = client.start_as_current_observation(**kwargs)
        observation = manager.__enter__()
    except Exception as exc:
        logger.warning("Langfuse observation start failed for {}: {}", name, exc)
        yield ObservationHandle(name=name)
        return

    handle = ObservationHandle(name=name, observation=observation)
    exc_info: tuple[Any, Any, Any] = (None, None, None)
    try:
        yield handle
    except BaseException as exc:
        exc_info = sys.exc_info()
        handle.update(level="ERROR", status_message=_safe_error_message(exc))
        raise
    finally:
        try:
            manager.__exit__(*exc_info)
        except Exception as exc:
            logger.warning("Langfuse observation close failed for {}: {}", name, exc)


def add_trace_attributes(
    *,
    trace_name: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> None:
    if not is_langfuse_configured():
        return

    try:
        from langfuse import propagate_attributes
    except ModuleNotFoundError:
        return
    except Exception as exc:
        logger.warning("Langfuse propagation import failed: {}", exc)
        return

    kwargs: dict[str, Any] = {"environment": settings.environment}
    if trace_name:
        kwargs["trace_name"] = trace_name
    if tags:
        kwargs["tags"] = tags

    try:
        with propagate_attributes(**kwargs):
            pass
    except Exception as exc:
        logger.warning("Langfuse trace attribute propagation failed: {}", exc)


def flush_langfuse() -> None:
    client = _get_langfuse_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception as exc:
        logger.warning("Langfuse flush failed: {}", exc)


def _get_langfuse_client() -> Optional[Any]:
    global _LANGFUSE_CLIENT, _LANGFUSE_CLIENT_CONFIG
    global _LANGFUSE_IMPORT_WARNING_LOGGED, _LANGFUSE_CONFIG_WARNING_LOGGED

    if not settings.langfuse_enabled:
        return None

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        if not _LANGFUSE_CONFIG_WARNING_LOGGED:
            logger.warning("Langfuse is enabled, but public or secret key is missing.")
            _LANGFUSE_CONFIG_WARNING_LOGGED = True
        return None

    config = (
        settings.langfuse_public_key,
        settings.langfuse_secret_key,
        settings.langfuse_base_url,
        settings.environment,
    )
    if _LANGFUSE_CLIENT is not None and _LANGFUSE_CLIENT_CONFIG == config:
        return _LANGFUSE_CLIENT

    try:
        from langfuse import Langfuse
    except ModuleNotFoundError:
        if not _LANGFUSE_IMPORT_WARNING_LOGGED:
            logger.warning("Langfuse SDK is not installed. Tracing is disabled.")
            _LANGFUSE_IMPORT_WARNING_LOGGED = True
        return None
    except Exception as exc:
        logger.warning("Langfuse SDK import failed. Tracing is disabled: {}", exc)
        return None

    try:
        _LANGFUSE_CLIENT = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url,
            environment=settings.environment,
        )
        _LANGFUSE_CLIENT_CONFIG = config
    except Exception as exc:
        logger.warning("Langfuse client initialization failed. Tracing is disabled: {}", exc)
        return None

    return _LANGFUSE_CLIENT


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _looks_sensitive_key(key: str) -> bool:
    normalized_key = key.casefold()
    sensitive_keys = (
        "api_key",
        "secret",
        "authorization",
        "cookie",
        "password",
        "access_token",
        "refresh_token",
        "id_token",
        "ssh_key",
    )
    return any(part in normalized_key for part in sensitive_keys)


def _safe_error_message(exc: BaseException) -> str:
    return mask_sensitive_text(f"{type(exc).__name__}: {exc}", limit=MAX_METADATA_TEXT_LENGTH)
