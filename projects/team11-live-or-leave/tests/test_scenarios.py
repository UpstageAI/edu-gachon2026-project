"""실제 dong_metrics.csv(서울 행정동 전체)로 선호도별 추천이 상식에 맞는지 검증.

test_scoring.py는 손으로 계산 가능한 합성 데이터로 알고리즘 자체를 검증했고,
여기서는 실제 데이터에 그 알고리즘을 태웠을 때 나오는 결과가 실세계 기준으로
말이 되는지(최저 범죄율, 접근성 상위, 밀도 argmax 등)를 확인한다.

주의: 개수형 지표는 인구 대비 '밀도'로 정규화되므로, "공원이 가장 많은 동"이
아니라 "인구 대비 공원이 가장 밀집한 동"이 1위가 될 수 있다 (설계상 의도,
HANDOFF.md 원칙 6). 그래서 raw count 최댓값이 아니라 밀도 argmax를 기준으로
검증한다.
"""
from __future__ import annotations

import pytest

from app.data.csv_repository import CsvDongRepository
from app.services import scoring

ONE_HOT = {
    "safety": {"safety": 1.0, "convenience": 0.0, "mobility": 0.0, "environment": 0.0},
    "convenience": {"safety": 0.0, "convenience": 1.0, "mobility": 0.0, "environment": 0.0},
    "mobility": {"safety": 0.0, "convenience": 0.0, "mobility": 1.0, "environment": 0.0},
    "environment": {"safety": 0.0, "convenience": 0.0, "mobility": 0.0, "environment": 1.0},
}
UNIFORM = {"safety": 0.25, "convenience": 0.25, "mobility": 0.25, "environment": 0.25}


@pytest.fixture(scope="module")
def real_raws():
    return CsvDongRepository().all_metrics()


@pytest.fixture(scope="module")
def real_scores(real_raws):
    return scoring.score_dongs(real_raws)


def _top1(scores, weights, **kw):
    return scoring.rank(scores, weights, top_n=1, **kw)[0]


# ---------- 카테고리별 극단 선호 → 해당 지표가 실제로 최상위인지 ----------

def test_safety_priority_picks_the_actual_lowest_crime_dong(real_raws, real_scores):
    top = _top1(real_scores, ONE_HOT["safety"])
    assert top.scores.raw.crime_rate == min(r.crime_rate for r in real_raws)


def test_convenience_priority_picks_facility_rich_dong_above_median(real_raws, real_scores):
    top = _top1(real_scores, ONE_HOT["convenience"])
    raw = top.scores.raw
    convs = sorted(r.conv_cnt for r in real_raws)
    marts = sorted(r.mart_cnt for r in real_raws)
    median_conv = convs[len(convs) // 2]
    median_mart = marts[len(marts) // 2]
    assert raw.conv_cnt > median_conv
    assert raw.mart_cnt > median_mart


def test_mobility_priority_picks_dong_with_decent_transit_access(real_raws, real_scores):
    top = _top1(real_scores, ONE_HOT["mobility"])
    raw = top.scores.raw
    buses = sorted(r.bus_cnt for r in real_raws)
    median_bus = buses[len(buses) // 2]
    # 버스·지하철 둘 다 median 밑일 수는 없다 (둘 중 하나는 강해야 이동 1위가 된다)
    assert raw.bus_cnt > median_bus or raw.subway_access > 0.5


def test_environment_priority_maximizes_park_density_not_raw_count(real_raws, real_scores):
    """밀도 argmax가 raw count 최댓값과 다를 수 있음을 확인 (설계 의도 재확인)."""
    top = _top1(real_scores, ONE_HOT["environment"])
    raw_max_park = max(real_raws, key=lambda r: r.park_cnt)

    top_density = top.scores.raw.park_cnt / top.scores.raw.population
    max_count_density = raw_max_park.park_cnt / raw_max_park.population
    assert top_density >= max_count_density

    # environment 점수 자체는 전체 중 최댓값(argmax)이어야 한다
    assert top.scores.environment == max(s.environment for s in real_scores)


# ---------- 서로 다른 선호는 서로 다른 동네를 추천해야 한다 ----------

def test_four_opposite_priorities_yield_mostly_distinct_top_picks(real_scores):
    picks = {cat: _top1(real_scores, w).dong for cat, w in ONE_HOT.items()}
    assert len(set(picks.values())) >= 3, f"선호를 바꿔도 추천이 거의 안 바뀜: {picks}"


# ---------- 균형 잡힌 선호 → 한쪽으로 치우치지 않은 추천 ----------

def test_uniform_preference_avoids_lopsided_recommendation(real_scores):
    top = _top1(real_scores, UNIFORM)
    s = top.scores
    for cat in scoring.CATEGORIES:
        assert getattr(s, cat) >= 0.5, (
            f"{cat} 점수가 {getattr(s, cat)}로 낮음 — 균등 선호인데 "
            f"한쪽으로 치우친 동네가 뽑혔다: {top.dong}")


# ---------- 데이터 불변식: 병원 보유 동은 실제 데이터의 진부분집합 ----------

def test_hospital_filter_is_a_proper_nonempty_subset_of_real_data(real_scores):
    filtered = [s for s in real_scores if s.raw.hosp_cnt >= 1]
    assert 0 < len(filtered) < len(real_scores)


# ---------- 데이터 불변식: 범죄율은 구 단위로 상속된다 ----------

def test_crime_rate_is_identical_within_same_gu(real_raws):
    by_gu: dict[str, set[float]] = {}
    for r in real_raws:
        by_gu.setdefault(r.gu, set()).add(r.crime_rate)
    offenders = {gu: vals for gu, vals in by_gu.items() if len(vals) > 1}
    assert not offenders, f"같은 구인데 범죄율이 다른 동이 있음: {offenders}"


# ---------- 랭킹 안정성 (실제 424개 규모에서) ----------

def test_recommendations_are_sorted_descending_on_real_data(real_scores):
    recs = scoring.rank(real_scores, UNIFORM, top_n=20)
    totals = [r.total_score for r in recs]
    assert totals == sorted(totals, reverse=True)


def test_top_n_prefix_is_stable_when_requesting_more_results(real_scores):
    top3 = scoring.rank(real_scores, UNIFORM, top_n=3)
    top10 = scoring.rank(real_scores, UNIFORM, top_n=10)
    assert [r.dong for r in top3] == [r.dong for r in top10[:3]]
