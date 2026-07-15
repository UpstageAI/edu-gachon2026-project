"""LLM client with deterministic model routing and fallback.

- Primary project model: Upstage Solar.
- Optional models: OpenAI/Gemini/Anthropic through LiteLLM.
- If the selected model fails, retry Solar first and then the remaining
  configured models before falling back to a local template response.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from langchain_upstage import ChatUpstage
from loguru import logger

from app.core.config import settings

TEMPERATURE = 0.3
DEFAULT_MODEL = "solar"


@dataclass(frozen=True)
class LLMFallbackResult:
    """Result of an LLM call after applying explicit model fallback."""

    message: Any
    model_id: str
    model_name: str | None
    attempted_models: list[str]
    fallback_used: bool


MODEL_REGISTRY: dict[str, dict[str, Any]] = {
    "solar": {
        "label": "Solar Pro",
        "provider": "upstage",
        "model": settings.llm_model,
        "key": settings.upstage_api_key,
    },
    "gpt-4o-mini": {
        "label": "GPT-4o mini",
        "provider": "litellm",
        "model": "gpt-4o-mini",
        "key": settings.openai_api_key,
        "env": "OPENAI_API_KEY",
    },
    "gemini-3.1-flash-lite": {
        "label": "Gemini 3.1 Flash-Lite",
        "provider": "litellm",
        "model": "gemini/gemini-3.1-flash-lite",
        "key": settings.gemini_api_key,
        "env": "GEMINI_API_KEY",
    },
    "claude-haiku": {
        "label": "Claude Haiku",
        "provider": "litellm",
        "model": "claude-3-5-haiku-latest",
        "key": settings.anthropic_api_key,
        "env": "ANTHROPIC_API_KEY",
    },
}


def available_models() -> list[dict[str, str]]:
    """Return models that have keys configured."""
    return [
        {"id": mid, "label": cfg["label"]}
        for mid, cfg in MODEL_REGISTRY.items()
        if cfg.get("key")
    ]


def _available_ids() -> list[str]:
    return [mid for mid, cfg in MODEL_REGISTRY.items() if cfg.get("key")]


def fallback_order(model_id: str | None = None) -> list[str]:
    """Return selected model -> Solar -> remaining configured models."""
    avail = _available_ids()
    if not avail:
        raise RuntimeError(
            "No available LLM. Configure at least one model key such as UPSTAGE_API_KEY."
        )

    order: list[str] = []
    if model_id in avail:
        order.append(model_id)
    if DEFAULT_MODEL in avail and DEFAULT_MODEL not in order:
        order.append(DEFAULT_MODEL)
    order.extend(mid for mid in avail if mid not in order)
    return order


def _build_one(model_id: str):
    """Build a single streaming chat model instance."""
    cfg = MODEL_REGISTRY[model_id]
    if cfg["provider"] == "upstage":
        return ChatUpstage(
            api_key=cfg["key"],
            model=cfg["model"],
            temperature=TEMPERATURE,
            streaming=True,
        )

    from langchain_litellm import ChatLiteLLM

    if cfg.get("env") and cfg.get("key"):
        os.environ.setdefault(cfg["env"], cfg["key"])
    return ChatLiteLLM(model=cfg["model"], temperature=TEMPERATURE, streaming=True)


async def ainvoke_with_fallback(
    messages: list[Any],
    *,
    model_id: str | None = None,
    timeout_seconds: float = 45,
) -> LLMFallbackResult:
    """Invoke a model and explicitly retry configured fallbacks.

    This is intentionally more explicit than LangChain's ``with_fallbacks`` so
    GPT quota/payment errors do not leak to the user and the actually used model
    is easy to report in SSE.
    """
    order = fallback_order(model_id)
    errors: list[str] = []
    last_exc: Exception | None = None

    for index, current_model_id in enumerate(order):
        try:
            llm = _build_one(current_model_id)
            response = await asyncio.wait_for(
                llm.ainvoke(messages),
                timeout=timeout_seconds,
            )
            meta = getattr(response, "response_metadata", None) or {}
            return LLMFallbackResult(
                message=response,
                model_id=current_model_id,
                model_name=meta.get("model_name") or meta.get("model"),
                attempted_models=order[: index + 1],
                fallback_used=index > 0,
            )
        except Exception as exc:
            last_exc = exc
            errors.append(f"{current_model_id}: {type(exc).__name__}")
            if index + 1 < len(order):
                logger.warning(
                    "LLM attempt failed; trying fallback "
                    f"(model={current_model_id}, error={type(exc).__name__})"
                )
            else:
                logger.warning(
                    "LLM attempt failed; no fallback left "
                    f"(model={current_model_id}, error={type(exc).__name__})"
                )

    raise RuntimeError("All LLM fallback attempts failed: " + " | ".join(errors)) from last_exc


@lru_cache
def get_llm(model_id: str | None = None):
    """Backward-compatible helper returning a model with LangChain fallbacks."""
    order = fallback_order(model_id)
    primary = _build_one(order[0])
    fallback_ids = order[1:]
    if not fallback_ids:
        return primary
    return primary.with_fallbacks([_build_one(mid) for mid in fallback_ids])
