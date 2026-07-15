"""Fail-open Langfuse score helpers for deterministic evaluations."""

from __future__ import annotations

from typing import Any

from app.core import observability
from app.core.config import Settings
from app.core.schemas import EvaluationResult


def _get_langfuse_client() -> Any:
    from langfuse import get_client

    return get_client()


def _score_payload(result: EvaluationResult) -> dict[str, Any]:
    return {
        "trace_id": result.trace_id,
        "name": result.eval_name,
        "value": result.score,
        "comment": "passed" if result.passed else "failed",
        "metadata": observability.sanitize_metadata(
            {
                "run_id": result.run_id,
                "run_date": result.run_date.isoformat() if result.run_date else None,
                "topic_id": result.topic_id,
                "passed": result.passed,
                "result": result.result,
            }
        ),
    }


def score_eval_result(
    result: EvaluationResult,
    *,
    settings: Settings | None = None,
) -> bool:
    """Send one evaluation result as a Langfuse score.

    Returns False when Langfuse is disabled, missing a trace id, or unavailable.
    Evaluation must never break report generation.
    """

    if not result.trace_id or result.score is None:
        return False
    if not observability.configure_langfuse_environment(settings):
        return False

    try:
        client = _get_langfuse_client()
        client.score(**_score_payload(result))
        return True
    except Exception:
        return False


def score_eval_results(
    results: list[EvaluationResult],
    *,
    settings: Settings | None = None,
) -> int:
    return len([item for item in results if score_eval_result(item, settings=settings)])
