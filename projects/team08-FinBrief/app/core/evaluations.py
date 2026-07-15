"""Deterministic run-level evaluations for FinBrief outputs."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from app.core.config import Settings, get_settings
from app.core.schemas import BatchRunResult, CardArtifact, EvaluationResult, IndicatorValue


DISCLAIMER_TOKEN = "투자 조언"


def _with_run_context(
    result: BatchRunResult,
    *,
    eval_name: str,
    score: float | None,
    passed: bool,
    detail: dict[str, Any],
    topic_id: str | None = None,
) -> EvaluationResult:
    return EvaluationResult(
        eval_name=eval_name,
        score=score,
        passed=passed,
        result=detail,
        run_id=result.run_id,
        run_date=result.run_date,
        trace_id=result.trace_id,
        topic_id=topic_id,
    )


def _text_fields(card: CardArtifact) -> list[str]:
    return [
        card.title,
        card.analysis.headline,
        card.analysis.summary,
        " ".join(card.analysis.key_points),
        card.analysis.disclaimer,
    ]


def _contains_forbidden(text: str, forbidden_terms: list[str]) -> list[str]:
    lowered = text.casefold()
    return [term for term in forbidden_terms if term and term.casefold() in lowered]


def _is_finite_number(value: float | None) -> bool:
    if value is None:
        return True
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _indicator_has_valid_numbers(indicator: IndicatorValue) -> bool:
    return all(
        _is_finite_number(value)
        for value in (
            indicator.current_value,
            indicator.previous_value,
            indicator.change_value,
            indicator.change_percent,
        )
    )


def _evaluate_disclaimer(result: BatchRunResult) -> EvaluationResult:
    missing: list[str] = []
    if result.report is None or DISCLAIMER_TOKEN not in result.report.disclaimer:
        missing.append("report")
    for card in result.generated_cards:
        if DISCLAIMER_TOKEN not in card.analysis.disclaimer:
            missing.append(card.topic_id)

    passed = not missing
    return _with_run_context(
        result,
        eval_name="safety.disclaimer",
        score=1.0 if passed else 0.0,
        passed=passed,
        detail={"missing": missing},
    )


def _evaluate_forbidden_terms(
    result: BatchRunResult,
    *,
    settings: Settings,
) -> EvaluationResult:
    violations: list[dict[str, Any]] = []
    for card in result.generated_cards:
        found = _contains_forbidden(" ".join(_text_fields(card)), settings.finbrief_llm_forbidden_terms)
        if found:
            violations.append({"topic_id": card.topic_id, "terms": found})

    passed = not violations
    return _with_run_context(
        result,
        eval_name="safety.forbidden_terms",
        score=1.0 if passed else 0.0,
        passed=passed,
        detail={"violations": violations},
    )


def _evaluate_evidence_coverage(result: BatchRunResult) -> EvaluationResult:
    total = len(result.generated_cards)
    covered = len([card for card in result.generated_cards if card.analysis.evidence])
    score = 1.0 if total == 0 else round(covered / total, 4)
    return _with_run_context(
        result,
        eval_name="rag.evidence_coverage",
        score=score,
        passed=covered == total,
        detail={"total_cards": total, "covered_cards": covered},
    )


def _evaluate_numeric_consistency(result: BatchRunResult) -> EvaluationResult:
    invalid: list[str] = []
    if result.report is not None:
        invalid = [
            item.indicator_id
            for item in result.report.indicators
            if not _indicator_has_valid_numbers(item)
        ]

    passed = not invalid
    return _with_run_context(
        result,
        eval_name="data.numeric_consistency",
        score=1.0 if passed else 0.0,
        passed=passed,
        detail={"invalid_indicators": invalid},
    )


def _evaluate_card_schema(result: BatchRunResult) -> EvaluationResult:
    invalid: list[str] = []
    for card in result.generated_cards:
        if not (
            card.card_id
            and card.topic_id
            and card.title
            and card.analysis.headline
            and card.analysis.summary
            and card.analysis.key_points
        ):
            invalid.append(card.topic_id)

    passed = not invalid
    return _with_run_context(
        result,
        eval_name="format.card_schema",
        score=1.0 if passed else 0.0,
        passed=passed,
        detail={"invalid_cards": invalid},
    )


def evaluate_batch_result(
    result: BatchRunResult,
    *,
    settings: Settings | None = None,
) -> list[EvaluationResult]:
    """Build deterministic safety/RAG/data/format checks for one report run."""

    cfg = settings or get_settings()
    return [
        _evaluate_disclaimer(result),
        _evaluate_forbidden_terms(result, settings=cfg),
        _evaluate_evidence_coverage(result),
        _evaluate_numeric_consistency(result),
        _evaluate_card_schema(result),
    ]


def eval_summary(results: list[EvaluationResult]) -> dict[str, Any]:
    passed = len([item for item in results if item.passed])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "scores": {
            item.eval_name: {
                "score": item.score,
                "passed": item.passed,
            }
            for item in results
        },
    }


def _date_to_iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def eval_run_rows(results: list[EvaluationResult]) -> list[dict[str, Any]]:
    """Serialize evaluation results for Supabase `eval_runs` inserts."""

    return [
        {
            "run_id": item.run_id,
            "run_date": _date_to_iso(item.run_date),
            "trace_id": item.trace_id,
            "topic_id": item.topic_id,
            "eval_name": item.eval_name,
            "score": item.score,
            "passed": item.passed,
            "result": item.result,
        }
        for item in results
    ]
