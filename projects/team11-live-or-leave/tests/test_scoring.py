"""services/scoring.py 단위 테스트 (합성 픽스처 — 실제 CSV와 독립)."""
from __future__ import annotations

import pytest

from app.schemas.tools import CategoryPreference, Importance
from app.services import scoring


# ---------- preference_to_weights ----------

def test_weights_sum_to_one():
    pref = CategoryPreference(
        safety=Importance.VERY_HIGH, convenience=Importance.HIGH,
        mobility=Importance.MEDIUM, environment=Importance.NONE)
    w = scoring.preference_to_weights(pref)
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_weights_proportional_to_importance_score():
    pref = CategoryPreference(
        safety=Importance.VERY_HIGH, convenience=Importance.HIGH,
        mobility=Importance.MEDIUM, environment=Importance.NONE)
    w = scoring.preference_to_weights(pref)
    # VERY_HIGH(1.0) : HIGH(0.6) : MEDIUM(0.3) 비율이 그대로 유지돼야 함
    assert w["safety"] == pytest.approx(1.0 / 1.9)
    assert w["convenience"] == pytest.approx(0.6 / 1.9)
    assert w["mobility"] == pytest.approx(0.3 / 1.9)
    assert w["environment"] == 0.0


def test_weights_extra_categories_join_the_same_sum_to_one_pool():
    pref = CategoryPreference(
        safety=Importance.VERY_HIGH, convenience=Importance.NONE,
        mobility=Importance.NONE, environment=Importance.NONE)
    w = scoring.preference_to_weights(pref, extra_categories=["버거"])
    # safety(1.0) : 버거(항상 VERY_HIGH=1.0) 비율 1:1 → 합=1 중 각각 절반
    assert w["safety"] == pytest.approx(0.5)
    assert w["버거"] == pytest.approx(0.5)
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_weights_extra_categories_alone_split_evenly_when_core_all_none():
    pref = CategoryPreference(
        safety=Importance.NONE, convenience=Importance.NONE,
        mobility=Importance.NONE, environment=Importance.NONE)
    w = scoring.preference_to_weights(pref, extra_categories=["버거", "헬스장"])
    assert w["버거"] == pytest.approx(0.5)
    assert w["헬스장"] == pytest.approx(0.5)
    assert w["safety"] == 0.0


def test_weights_without_extra_categories_only_has_core_keys():
    pref = CategoryPreference(
        safety=Importance.HIGH, convenience=Importance.NONE,
        mobility=Importance.NONE, environment=Importance.NONE)
    w = scoring.preference_to_weights(pref)
    assert set(w.keys()) == set(scoring.CATEGORIES)


# ---------- score_extra_categories ----------

def test_score_extra_categories_percentile_normalizes_density(sample_raws):
    # sample_raws의 A1/B1/C1은 population이 전부 10000이라 density == count
    extra_counts = {"버거": {"A1": 3, "B1": 1, "C1": 2}}
    scores = scoring.score_extra_categories(sample_raws, extra_counts)
    assert scores["버거"] == {"A1": 1.0, "B1": 0.0, "C1": 0.5}


def test_score_extra_categories_missing_code_defaults_to_zero_count(sample_raws):
    extra_counts = {"버거": {"A1": 5}}  # B1, C1은 언급 없음 → 0으로 취급
    scores = scoring.score_extra_categories(sample_raws, extra_counts)
    assert scores["버거"]["B1"] == 0.0
    assert scores["버거"]["A1"] == 1.0


def test_weights_all_none_falls_back_to_uniform():
    pref = CategoryPreference(
        safety=Importance.NONE, convenience=Importance.NONE,
        mobility=Importance.NONE, environment=Importance.NONE)
    w = scoring.preference_to_weights(pref)
    assert w == {"safety": 0.25, "convenience": 0.25, "mobility": 0.25, "environment": 0.25}


# ---------- _percentile_norm ----------

def test_percentile_norm_single_value_is_midpoint():
    assert scoring._percentile_norm({"a": 42}) == {"a": 0.5}


def test_percentile_norm_orders_ascending_to_0_1():
    out = scoring._percentile_norm({"lo": 1, "mid": 5, "hi": 10})
    assert out == {"lo": 0.0, "mid": 0.5, "hi": 1.0}


def test_percentile_norm_invert_flips_order():
    out = scoring._percentile_norm({"lo": 1, "mid": 5, "hi": 10}, invert=True)
    assert out == {"lo": 1.0, "mid": 0.5, "hi": 0.0}


# ---------- score_dongs ----------

def test_score_dongs_matches_hand_computed_values(sample_raws):
    scores = {s.code: s for s in scoring.score_dongs(sample_raws)}

    assert scores["A1"].safety == 1.0
    assert scores["A1"].convenience == 0.5
    assert scores["A1"].mobility == 1.0
    assert scores["A1"].environment == 1.0

    assert scores["B1"].safety == 0.0
    assert scores["B1"].convenience == 0.3
    assert scores["B1"].mobility == 0.0
    assert scores["B1"].environment == 0.0

    assert scores["C1"].safety == 0.5
    assert scores["C1"].convenience == 0.7
    assert scores["C1"].mobility == 0.5
    assert scores["C1"].environment == 0.5


def test_score_dongs_all_scores_within_unit_range(sample_raws):
    for s in scoring.score_dongs(sample_raws):
        for cat in scoring.CATEGORIES:
            assert 0.0 <= getattr(s, cat) <= 1.0


def test_score_dongs_density_uses_population_not_raw_count():
    """같은 raw count라도 인구가 다르면 밀도(및 점수)가 달라져야 한다.

    편의 점수는 conv/mart/hosp 세 지표를 합성하므로, 세 지표 모두
    밀집동 쪽이 더 높게 설계해 밀도 방향에 노이즈(동률)가 없게 한다.
    """
    from tests.conftest import _raw

    dense = _raw("P1", "밀집동", "A구", population=5000,
                  conv_cnt=50, mart_cnt=10, hosp_cnt=2)
    sparse = _raw("P2", "희소동", "A구", population=50000,
                   conv_cnt=50, mart_cnt=10, hosp_cnt=2)
    scores = {s.code: s for s in scoring.score_dongs([dense, sparse])}
    assert scores["P1"].convenience > scores["P2"].convenience


# ---------- rank ----------

def test_rank_orders_by_weighted_total(sample_raws):
    scores = scoring.score_dongs(sample_raws)
    weights = {"safety": 1.0, "convenience": 0.0, "mobility": 0.0, "environment": 0.0}
    recs = scoring.rank(scores, weights, top_n=3)
    assert [r.dong for r in recs] == ["A동", "C동", "B동"]
    assert recs[0].total_score == 1.0
    assert recs[1].total_score == 0.5
    assert recs[2].total_score == 0.0


def test_rank_top_n_limits_result_count(sample_raws):
    scores = scoring.score_dongs(sample_raws)
    weights = {"safety": 0.25, "convenience": 0.25, "mobility": 0.25, "environment": 0.25}
    recs = scoring.rank(scores, weights, top_n=2)
    assert len(recs) == 2
    assert [r.rank for r in recs] == [1, 2]


def test_rank_merges_extra_scores_into_contributions_and_total(sample_raws):
    scores = scoring.score_dongs(sample_raws)
    weights = {"safety": 0.0, "convenience": 0.0, "mobility": 0.0, "environment": 0.0, "버거": 1.0}
    extra_scores = {"버거": {"A1": 1.0, "B1": 0.0, "C1": 0.5}}
    recs = scoring.rank(scores, weights, top_n=3, extra_scores=extra_scores)
    assert [r.dong for r in recs] == ["A동", "C동", "B동"]
    assert recs[0].contributions["버거"] == 1.0
    assert recs[0].total_score == 1.0


def test_rank_without_extra_scores_has_no_extra_keys_in_contributions(sample_raws):
    scores = scoring.score_dongs(sample_raws)
    weights = {"safety": 1.0, "convenience": 0.0, "mobility": 0.0, "environment": 0.0}
    recs = scoring.rank(scores, weights, top_n=1)
    assert set(recs[0].contributions.keys()) == set(scoring.CATEGORIES)
