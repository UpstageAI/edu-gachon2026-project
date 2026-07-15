"""Shared report run lookup/storage service for API, scheduler, and bot."""

from __future__ import annotations

from datetime import date

from app.agents.pipeline import get_latest_result
from app.core.schemas import BatchRunResult
from app.repositories.protocols import RepositoryBundle


def store_report_result(repos: RepositoryBundle, result: BatchRunResult) -> bool:
    """Persist a report run without leaking repository details to callers."""

    repos.reports.upsert(result)
    return True


def get_report_result(
    repos: RepositoryBundle,
    *,
    run_date: date | None = None,
    run_id: str | None = None,
) -> BatchRunResult | None:
    """Return a report run from shared storage first, then local fallback."""

    if run_id:
        stored = repos.reports.get_by_run_id(run_id)
        if stored is not None:
            return stored
        return get_latest_result(run_date)
    if run_date:
        stored = repos.reports.get_by_date(run_date)
        if stored is not None:
            return stored
        return get_latest_result(run_date)
    stored = repos.reports.get_latest()
    if stored is not None:
        return stored
    return get_latest_result()
