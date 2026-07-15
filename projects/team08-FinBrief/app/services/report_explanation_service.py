"""Cached report explanation service."""

from __future__ import annotations

from app.core.schemas import BatchRunResult
from app.repositories.protocols import RepositoryBundle
from app.services.report_explainer import build_report_explanation


def get_or_build_report_explanation(
    repos: RepositoryBundle,
    *,
    result: BatchRunResult,
    max_focus: int = 3,
    refresh: bool = False,
) -> dict[str, object]:
    """Return a cached report explanation or build and persist one."""

    if not refresh:
        cached = repos.report_explanations.get_by_run_id(result.run_id)
        if cached is not None:
            return {**cached, "run_id": result.run_id, "cached": True}

    payload = build_report_explanation(result, repos=repos, max_focus=max_focus)
    payload = {**payload, "run_id": result.run_id}
    repos.report_explanations.upsert(result.run_id, payload)
    return {**payload, "cached": False}
