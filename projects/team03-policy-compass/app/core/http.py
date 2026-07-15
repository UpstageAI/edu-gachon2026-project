from __future__ import annotations

import logging

import httpx


def log_external_api_error(logger: logging.Logger, api_name: str, exc: Exception) -> None:
    """Log an external API failure without URLs, query strings, or credentials."""

    status = None
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
    suffix = f", status={status}" if status is not None else ""
    logger.warning("%s 호출 실패 (error=%s%s)", api_name, type(exc).__name__, suffix)
