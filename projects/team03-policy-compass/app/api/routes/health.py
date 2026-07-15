from __future__ import annotations

import os
from urllib.parse import urlparse

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings

router = APIRouter(tags=["health"])


def _is_configured(value: object) -> bool:
    """Return configuration presence without ever serializing the value."""

    return bool(value and str(value).strip())


def _is_http_url(value: object) -> bool:
    if not _is_configured(value):
        return False
    parsed = urlparse(str(value).strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _readiness_payload() -> tuple[dict[str, object], bool]:
    settings = get_settings()
    configured = {
        "upstage": _is_configured(settings.upstage_api_key) and _is_http_url(settings.upstage_base_url),
        "youthcenter": _is_configured(settings.youthcenter_policy_api_key)
        and _is_http_url(settings.youthcenter_policy_api_url),
        "work24_training": _is_configured(settings.employment24_training_api_key)
        and _is_http_url(settings.employment24_training_api_url),
        "work24_job": _is_configured(settings.employment24_job_api_key)
        and _is_http_url(settings.employment24_job_event_api_url)
        and _is_http_url(settings.employment24_open_recruitment_api_url),
        "supabase": _is_http_url(settings.supabase_url) and _is_configured(settings.supabase_key),
    }
    dependencies = {
        name: {"status": "configured" if is_configured else "not_configured"}
        for name, is_configured in configured.items()
    }
    missing_dependencies = [name for name, is_configured in configured.items() if not is_configured]
    is_ready = not missing_dependencies
    is_production = settings.app_env.strip().lower() == "production"
    status = "ready" if is_ready else "not_ready" if is_production else "degraded"

    return (
        {
            "status": status,
            "release_sha": os.getenv("APP_RELEASE_SHA", "unknown").strip() or "unknown",
            "app_env": settings.app_env,
            "dependencies": dependencies,
            "missing_dependencies": missing_dependencies,
        },
        is_ready or not is_production,
    )


@router.get("/health")
async def health_check() -> dict[str, str]:
    settings = get_settings()
    langfuse_tracing = "enabled" if settings.langfuse_public_key and settings.langfuse_secret_key else "disabled"
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "langfuse_tracing": langfuse_tracing,
    }


@router.get("/live")
async def liveness_check() -> dict[str, str]:
    """Process-only liveness probe; it deliberately does not inspect dependencies."""

    return {"status": "alive"}


@router.get("/ready", response_model=None)
async def readiness_check() -> dict[str, object] | JSONResponse:
    """Report configuration readiness without exposing credentials or endpoints."""

    payload, acceptable = _readiness_payload()
    if acceptable:
        return payload
    return JSONResponse(status_code=503, content=payload)
