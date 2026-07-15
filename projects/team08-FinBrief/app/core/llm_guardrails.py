"""Small app-level guardrails for FinBrief LLM outputs.

The project currently calls LiteLLM through the Python SDK, so these checks keep
the MVP safe without requiring a separate LiteLLM Proxy process.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any

from app.core.config import Settings, get_settings


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
WEBHOOK_RE = re.compile(
    r"https://(?:discord(?:app)?\.com/api/webhooks|hooks\.slack\.com/services)/[^\s\"'<>]+",
    re.IGNORECASE,
)
API_KEY_RE = re.compile(r"\b(?:sk|pk|upstage|ghp|github_pat)_[A-Za-z0-9_\-]{12,}\b")

CARD_REQUIRED_KEYS = {"headline", "lead", "body", "source"}


@dataclass
class GuardrailResult:
    status: str
    reason: str | None = None
    details: dict[str, Any] | None = None


class GuardrailViolation(RuntimeError):
    """Raised when LLM input/output violates the FinBrief safety contract."""

    def __init__(self, reason: str, details: dict[str, Any] | None = None):
        self.reason = reason
        self.details = details or {}
        super().__init__(reason)


def mask_sensitive_text(text: str) -> str:
    """Mask obvious PII/secrets before sending text to an LLM or trace."""

    masked = EMAIL_RE.sub("[EMAIL_REDACTED]", str(text))
    masked = WEBHOOK_RE.sub("[WEBHOOK_REDACTED]", masked)
    return API_KEY_RE.sub("[SECRET_REDACTED]", masked)


def _mask_value(value: Any) -> Any:
    if isinstance(value, str):
        return mask_sensitive_text(value)
    if isinstance(value, list):
        return [_mask_value(item) for item in value]
    if isinstance(value, tuple):
        return [_mask_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _mask_value(item) for key, item in value.items()}
    return value


def _iter_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        items: list[str] = []
        for item in value.values():
            items.extend(_iter_strings(item))
        return items
    if isinstance(value, (list, tuple)):
        items = []
        for item in value:
            items.extend(_iter_strings(item))
        return items
    return []


def prepare_prompt(system: str, user: str, settings: Settings | None = None) -> tuple[str, str]:
    """Validate and optionally mask prompt text before a LiteLLM request."""

    cfg = settings or get_settings()
    if not str(system).strip() or not str(user).strip():
        raise GuardrailViolation("empty_messages")
    if not cfg.finbrief_llm_guardrail_enabled or not cfg.finbrief_llm_pii_masking:
        return system, user
    return mask_sensitive_text(system), mask_sensitive_text(user)


def validate_json_payload(
    payload: dict[str, Any],
    *,
    profile: str = "generic",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Validate an LLM JSON payload and return a sanitized copy."""

    cfg = settings or get_settings()
    if not isinstance(payload, dict):
        raise GuardrailViolation("schema_error", {"expected": "object"})

    result = deepcopy(payload)
    if cfg.finbrief_llm_guardrail_enabled and cfg.finbrief_llm_pii_masking:
        result = _mask_value(result)

    if not cfg.finbrief_llm_guardrail_enabled:
        return result

    if profile == "card" and cfg.finbrief_llm_require_json:
        missing = sorted(CARD_REQUIRED_KEYS - set(result))
        if missing:
            raise GuardrailViolation("schema_error", {"missing_keys": missing})

    forbidden = sorted(
        {
            term
            for term in cfg.finbrief_llm_forbidden_terms
            if term and any(term in text for text in _iter_strings(result))
        }
    )
    if forbidden:
        raise GuardrailViolation("forbidden_terms", {"terms": forbidden})

    return result
