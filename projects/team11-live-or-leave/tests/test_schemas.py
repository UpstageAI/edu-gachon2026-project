"""schemas/domain.py, schemas/tools.py 제약 검증."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.domain import DongRawMetrics, DongScores
from app.schemas.tools import (
    IMPORTANCE_SCORE,
    CategoryPreference,
    Importance,
    ParsedIntent,
)


def _raw_kwargs(**overrides):
    base = dict(
        code="1", dong="d", gu="g", population=1000,
        crime_rate=1.0, cctv_cnt=1, conv_cnt=1, mart_cnt=1,
        hosp_cnt=1, bus_cnt=1, subway_access=0.5, park_cnt=1,
    )
    base.update(overrides)
    return base


# ---------- IMPORTANCE_SCORE / Importance ----------

def test_importance_score_strictly_ordered():
    assert (IMPORTANCE_SCORE[Importance.VERY_HIGH]
            > IMPORTANCE_SCORE[Importance.HIGH]
            > IMPORTANCE_SCORE[Importance.MEDIUM]
            > IMPORTANCE_SCORE[Importance.NONE])


def test_importance_score_exact_values():
    assert IMPORTANCE_SCORE[Importance.VERY_HIGH] == 1.0
    assert IMPORTANCE_SCORE[Importance.HIGH] == 0.6
    assert IMPORTANCE_SCORE[Importance.MEDIUM] == 0.3
    assert IMPORTANCE_SCORE[Importance.NONE] == 0.0


# ---------- CategoryPreference ----------

def test_category_preference_requires_all_four_categories():
    with pytest.raises(ValidationError):
        CategoryPreference(safety=Importance.HIGH, convenience=Importance.HIGH,
                            mobility=Importance.HIGH)  # environment 누락


def test_category_preference_rejects_invalid_label():
    with pytest.raises(ValidationError):
        CategoryPreference(safety="extreme", convenience=Importance.HIGH,
                            mobility=Importance.HIGH, environment=Importance.HIGH)


# ---------- ParsedIntent ----------

def test_parsed_intent_defaults():
    pref = CategoryPreference(safety=Importance.NONE, convenience=Importance.NONE,
                               mobility=Importance.NONE, environment=Importance.NONE)
    intent = ParsedIntent(preference=pref)
    assert intent.extra_categories == []
    assert intent.needs_clarification is False
    assert intent.clarify_question is None


# ---------- DongRawMetrics ----------

def test_dong_raw_metrics_rejects_zero_or_negative_population():
    with pytest.raises(ValidationError):
        DongRawMetrics(**_raw_kwargs(population=0))


def test_dong_raw_metrics_rejects_negative_counts():
    with pytest.raises(ValidationError):
        DongRawMetrics(**_raw_kwargs(cctv_cnt=-1))


def test_dong_raw_metrics_rejects_subway_access_out_of_range():
    with pytest.raises(ValidationError):
        DongRawMetrics(**_raw_kwargs(subway_access=1.5))
    with pytest.raises(ValidationError):
        DongRawMetrics(**_raw_kwargs(subway_access=-0.1))


def test_dong_raw_metrics_accepts_valid_values():
    m = DongRawMetrics(**_raw_kwargs())
    assert m.population == 1000


# ---------- DongScores ----------

def test_dong_scores_rejects_out_of_unit_range():
    raw = DongRawMetrics(**_raw_kwargs())
    with pytest.raises(ValidationError):
        DongScores(code="1", dong="d", gu="g", safety=1.5,
                    convenience=0.5, mobility=0.5, environment=0.5, raw=raw)
