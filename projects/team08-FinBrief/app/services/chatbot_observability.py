"""Fail-open Langfuse tracing helpers for Discord chatbot turns."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from typing import Any, Iterator

from app.core import langfuse_scores, llm_guardrails, observability
from app.core.config import Settings, get_settings
from app.core.schemas import EvaluationResult


MAX_CAPTURED_TEXT = 1200
CHATBOT_TAGS = ["finbrief", "chatbot"]


def _secret_value(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        return str(value.get_secret_value())
    return str(value)


def _salt(settings: Settings) -> str:
    return _secret_value(getattr(settings, "finbrief_trace_salt", None)) or settings.app_name


def _digest(value: str, settings: Settings) -> str:
    payload = f"{_salt(settings)}:{value}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def hash_identifier(
    value: object | None,
    *,
    settings: Settings | None = None,
    prefix: str = "id",
    length: int = 16,
) -> str | None:
    """Return a salted hash suitable for trace metadata."""

    if value is None or value == "":
        return None
    cfg = settings or get_settings()
    return f"{prefix}_{_digest(str(value), cfg)[:length]}"


def capture_text(text: str, settings: Settings | None = None) -> str | None:
    """Return masked text only when Langfuse IO capture is enabled."""

    cfg = settings or get_settings()
    if not cfg.langfuse_capture_io:
        return None
    return llm_guardrails.mask_sensitive_text(str(text))[:MAX_CAPTURED_TEXT]


def turn_id_for(
    *,
    channel: str,
    ext_user_id: str,
    message: str,
    channel_id: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Build a deterministic turn id without exposing raw Discord identifiers."""

    cfg = settings or get_settings()
    seed = "|".join(
        [
            str(channel),
            hash_identifier(ext_user_id, settings=cfg, prefix="usr") or "",
            hash_identifier(channel_id, settings=cfg, prefix="ch") or "",
            hash_identifier(message, settings=cfg, prefix="msg") or "",
        ]
    )
    return f"chatbot_turn_{_digest(seed, cfg)[:20]}"


def build_turn_metadata(
    *,
    channel: str,
    ext_user_id: str,
    channel_id: str | None,
    message: str,
    settings: Settings | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build sanitized metadata for a chatbot turn trace."""

    cfg = settings or get_settings()
    metadata: dict[str, Any] = {
        "channel": channel,
        "user_hash": hash_identifier(ext_user_id, settings=cfg, prefix="usr"),
        "channel_hash": hash_identifier(channel_id, settings=cfg, prefix="ch"),
        "message_hash": hash_identifier(message, settings=cfg, prefix="msg"),
        "message_length": len(str(message)),
        "capture_io": cfg.langfuse_capture_io,
        "captured_message": capture_text(message, cfg),
        "app_env": cfg.app_env,
        "enable_mock_data": cfg.enable_mock_data,
        "tags": CHATBOT_TAGS,
    }
    if extra:
        metadata.update(extra)
    return observability.sanitize_metadata(metadata)


@contextmanager
def chatbot_turn_trace(
    *,
    channel: str,
    ext_user_id: str,
    message: str,
    channel_id: str | None = None,
    settings: Settings | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[tuple[str, str, Any]]:
    """Open a root chatbot turn observation and yield `(trace_id, turn_id, observation)`."""

    cfg = settings or get_settings()
    turn_id = turn_id_for(
        channel=channel,
        ext_user_id=ext_user_id,
        message=message,
        channel_id=channel_id,
        settings=cfg,
    )
    trace_id = observability.trace_id_for_run(turn_id, cfg)
    trace_metadata = build_turn_metadata(
        channel=channel,
        ext_user_id=ext_user_id,
        channel_id=channel_id,
        message=message,
        settings=cfg,
        extra={"turn_id": turn_id, "trace_id": trace_id, **(metadata or {})},
    )

    if not observability.configure_langfuse_environment(cfg):
        yield trace_id, turn_id, observability.NoopObservation()
        return

    try:
        from langfuse import get_client

        langfuse = get_client()
        observation_cm = langfuse.start_as_current_observation(
            as_type="span",
            name="finbrief.chatbot.turn",
            trace_context={"trace_id": trace_id},
        )
        observation = observation_cm.__enter__()
    except Exception:
        yield trace_id, turn_id, observability.NoopObservation()
        return

    try:
        try:
            observation.update(metadata=trace_metadata, input=capture_text(message, cfg))
        except Exception:
            pass
        yield trace_id, turn_id, observation
    finally:
        try:
            observation_cm.__exit__(None, None, None)
        except Exception:
            pass
        if cfg.langfuse_flush_on_shutdown:
            try:
                langfuse.flush()
            except Exception:
                pass


def build_chatbot_llm_metadata(
    *,
    trace_id: str | None,
    turn_id: str | None,
    node: str,
    message: str | None = None,
    extra: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Build LiteLLM metadata for chatbot LLM calls."""

    cfg = settings or get_settings()
    payload: dict[str, Any] = {
        "message_hash": hash_identifier(message, settings=cfg, prefix="msg") if message else None,
        "message_length": len(str(message)) if message is not None else None,
    }
    if extra:
        payload.update(extra)
    return observability.build_llm_metadata(
        trace_id=trace_id,
        run_id=turn_id,
        node=node,
        tags=[*CHATBOT_TAGS, node],
        extra=payload,
    )


def score_chatbot_turn(
    eval_name: str,
    *,
    score: float,
    passed: bool,
    trace_id: str | None,
    turn_id: str | None,
    metadata: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> bool:
    """Send a deterministic chatbot score to Langfuse without affecting replies."""

    result = EvaluationResult(
        eval_name=eval_name,
        score=score,
        passed=passed,
        run_id=turn_id,
        trace_id=trace_id,
        result=observability.sanitize_metadata(metadata or {}),
    )
    return langfuse_scores.score_eval_result(result, settings=settings)
