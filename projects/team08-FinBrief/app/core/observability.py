"""Langfuse/LiteLLM observability helpers.

The helpers in this module are intentionally defensive: observability must not
break the report pipeline when Langfuse is disabled, misconfigured, unavailable,
or not installed in a local test environment.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
import re
from typing import Any, Iterator

from app.core.config import Settings, get_settings


_SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|secret|token|webhook|password|credential|service[_-]?role)",
    re.IGNORECASE,
)


class NoopObservation:
    """Small stand-in for Langfuse observation objects."""

    def update(self, **_: Any) -> None:
        return None

    def update_trace(self, **_: Any) -> None:
        return None

    def set_trace_io(self, **_: Any) -> None:
        return None

    def score_trace(self, **_: Any) -> None:
        return None


def _secret_value(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        return str(value.get_secret_value())
    return str(value)


def sanitize_metadata(value: Any) -> Any:
    """Return metadata with obvious secret-bearing fields redacted."""

    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _SENSITIVE_KEY.search(str(key)):
                cleaned[str(key)] = "[redacted]"
            else:
                cleaned[str(key)] = sanitize_metadata(item)
        return cleaned
    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_metadata(item) for item in value]
    return value


def langfuse_ready(settings: Settings | None = None) -> bool:
    """Return True only when Langfuse is enabled and credentials are present."""

    cfg = settings or get_settings()
    return bool(
        cfg.langfuse_enabled
        and cfg.langfuse_public_key
        and _secret_value(cfg.langfuse_secret_key)
    )


def configure_langfuse_environment(settings: Settings | None = None) -> bool:
    """Map FinBrief settings to Langfuse SDK/LiteLLM OTEL environment variables."""

    cfg = settings or get_settings()
    if not langfuse_ready(cfg):
        return False

    secret_key = _secret_value(cfg.langfuse_secret_key)
    if not secret_key:
        return False

    base_url = os.getenv("LANGFUSE_BASE_URL") or cfg.langfuse_host
    otel_host = os.getenv("LANGFUSE_OTEL_HOST") or base_url

    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", str(cfg.langfuse_public_key))
    os.environ.setdefault("LANGFUSE_SECRET_KEY", secret_key)
    os.environ.setdefault("LANGFUSE_BASE_URL", base_url)
    os.environ.setdefault("LANGFUSE_OTEL_HOST", otel_host)
    return True


def configure_litellm_callbacks(litellm_module: Any, settings: Settings | None = None) -> bool:
    """Enable LiteLLM's Langfuse OTEL callback when Langfuse is configured."""

    if not configure_langfuse_environment(settings):
        return False

    callbacks = list(getattr(litellm_module, "callbacks", []) or [])
    if "langfuse_otel" not in callbacks:
        callbacks.append("langfuse_otel")
    litellm_module.callbacks = callbacks
    return True


def trace_id_for_run(run_id: str, settings: Settings | None = None) -> str:
    """Return a stable trace id for a FinBrief run."""

    cfg = settings or get_settings()
    if not langfuse_ready(cfg):
        return f"local_mock_trace_{run_id}"

    try:
        from langfuse import Langfuse

        return str(Langfuse.create_trace_id(seed=run_id))
    except Exception:
        return f"local_trace_{run_id}"


def build_llm_metadata(
    *,
    trace_id: str | None,
    run_id: str | None,
    topic_id: str | None = None,
    node: str,
    tags: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build metadata that LiteLLM's Langfuse OTEL callback can export."""

    metadata: dict[str, Any] = {
        "generation_name": f"{node}:{topic_id}" if topic_id else node,
        "trace_id": trace_id,
        "session_id": run_id,
        "topic_id": topic_id,
        "node": node,
        "tags": tags or ["finbrief"],
    }
    if extra:
        metadata.update(extra)
    return sanitize_metadata({k: v for k, v in metadata.items() if v is not None})


def _safe_update(observation: Any, **payload: Any) -> None:
    try:
        observation.update(**payload)
    except Exception:
        return None


@contextmanager
def span(
    name: str,
    *,
    settings: Settings | None = None,
    metadata: dict[str, Any] | None = None,
    input: Any | None = None,
    as_type: str = "span",
) -> Iterator[Any]:
    """Start a Langfuse observation or a no-op observation."""

    if not configure_langfuse_environment(settings):
        yield NoopObservation()
        return

    try:
        from langfuse import get_client

        langfuse = get_client()
        with langfuse.start_as_current_observation(as_type=as_type, name=name) as observation:
            payload: dict[str, Any] = {}
            if metadata is not None:
                payload["metadata"] = sanitize_metadata(metadata)
            if input is not None:
                payload["input"] = sanitize_metadata(input)
            if payload:
                _safe_update(observation, **payload)
            yield observation
    except Exception:
        yield NoopObservation()


@contextmanager
def report_trace(
    *,
    run_id: str,
    run_date: str,
    settings: Settings | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[tuple[str, Any]]:
    """Open the root report trace and yield `(trace_id, observation)`."""

    cfg = settings or get_settings()
    trace_id = trace_id_for_run(run_id, cfg)
    if not configure_langfuse_environment(cfg):
        yield trace_id, NoopObservation()
        return

    trace_metadata = {
        "run_id": run_id,
        "run_date": run_date,
        "app_env": cfg.app_env,
        "enable_mock_data": cfg.enable_mock_data,
    }
    if metadata:
        trace_metadata.update(metadata)

    try:
        from langfuse import get_client

        langfuse = get_client()
        with langfuse.start_as_current_observation(
            as_type="span",
            name="finbrief.report.run",
            trace_context={"trace_id": trace_id},
        ) as observation:
            _safe_update(observation, metadata=sanitize_metadata(trace_metadata))
            yield trace_id, observation
        if cfg.langfuse_flush_on_shutdown:
            try:
                langfuse.flush()
            except Exception:
                pass
    except Exception:
        yield trace_id, NoopObservation()
