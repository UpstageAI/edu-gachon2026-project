"""Lazy Supabase client creation.

This module must be safe to import without Supabase environment variables.
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings, get_settings


class SupabaseSettingsError(RuntimeError):
    """Raised when a Supabase repository is requested without valid settings."""


def _secret_value(value: object) -> str | None:
    if value is None:
        return None
    get_secret_value = getattr(value, "get_secret_value", None)
    if callable(get_secret_value):
        return get_secret_value()
    return str(value)


def create_supabase_client(settings: Settings | None = None) -> Any:
    """Create a Supabase client only when explicitly requested."""

    runtime_settings = settings or get_settings()
    if not runtime_settings.supabase_url:
        raise SupabaseSettingsError("SUPABASE_URL is required")

    service_role_key = _secret_value(runtime_settings.supabase_service_role_key)
    if not service_role_key:
        raise SupabaseSettingsError("SUPABASE_SERVICE_ROLE_KEY is required")

    try:
        from supabase import create_client
    except ModuleNotFoundError as exc:
        raise SupabaseSettingsError(
            "supabase package is not installed. Run python -m pip install -e \".[dev]\"."
        ) from exc

    return create_client(runtime_settings.supabase_url, service_role_key)
