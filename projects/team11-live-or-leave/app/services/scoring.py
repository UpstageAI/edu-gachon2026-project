"""
서비스 계층 — 결정론적 계산 (행정동 단위). LLM 개입 없음.

정규화: 분위수(백분위) 방식 — 이상치에 강건.
개수형 지표는 인구 대비 밀도로 환산 후 분위수 정규화.
지하철은 이미 0~1 접근성이라 그대로.
범죄는 낮을수록 좋음(invert).
"""
from __future__ import annotations

from app.schemas.domain import DongRawMetrics, DongScores, Recommendation
from app.schemas.tools import IMPORTANCE_SCORE, CategoryPreference, Importance

CATEGORIES = ("safety", "convenience", "mobility", "environment")


def preference_to_weights(
    pref: CategoryPreference, extra_categories: list[str] | None = None
) -> dict[str, float]:
    """라벨(4단계) → 가중치. extra_categories는 사용자가 명시적으로 언급한
    임의 업종이라 항상 '매우 중요'로 취급해 같은 합=1 정규화에 합류시킨다."""
    raw = {c: IMPORTANCE_SCORE[getattr(pref, c)] for c in CATEGORIES}
    for cat in extra_categories or []:
        raw[cat] = IMPORTANCE_SCORE[Importance.VERY_HIGH]
    total = sum(raw.values())
    if total == 0:
        return {c: 1 / len(raw) for c in raw}
    return {c: v / total for c, v in raw.items()}


def score_extra_categories(
    raws: list[DongRawMetrics], extra_counts: dict[str, dict[str, int]]
) -> dict[str, dict[str, float]]:
    """임의 업종별 (행정동코드 → 백분위 점수). 기존 4개 카테고리와 동일하게
    생활인구 대비 밀도로 환산 후 분위수 정규화한다."""
    result = {}
    for cat, counts in extra_counts.items():
        density = {r.code: counts.get(r.code, 0) / r.population * 10000 for r in raws}
        result[cat] = _percentile_norm(density)
    return result


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """(lon, lat) 두 점 사이 대원거리(km)."""
    from math import asin, cos, radians, sin, sqrt

    lon1, lat1, lon2, lat2 = map(radians, (*a, *b))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(h))


def partition_by_proximity(
    scores: list[DongScores],
    landmarks: dict[str, tuple[float, float]],
    centroids: dict[str, tuple[float, float]],
    radius_km: float,
) -> tuple[list[DongScores], list[dict]]:
    """'서울대 근처' 류 거리 필수조건 — 모든 랜드마크에서 radius_km 이내
    (동 중심점 기준)인 동만 통과. (qualified, disqualified+사유) 반환 형태."""
    qualified = []
    disqualified = []
    for s in scores:
        c = centroids.get(s.code)
        missing = [
            f"{name} 근처({radius_km:g}km 이내) 아님"
            for name, coord in landmarks.items()
            if c is None or haversine_km(c, coord) > radius_km
        ]
        if missing:
            disqualified.append({"scores": s, "missing": missing})
        else:
            qualified.append(s)
    return qualified, disqualified


def _percentile_norm(values: dict[str, float], invert: bool = False) -> dict[str, float]:
    """백분위 정규화 (0~1). invert=True면 낮을수록 1점."""
    items = sorted(values.items(), key=lambda x: x[1])
    n = len(items)
    out = {}
    for rank, (k, _) in enumerate(items):
        p = rank / (n - 1) if n > 1 else 0.5
        out[k] = 1 - p if invert else p
    return out


def score_dongs(raws: list[DongRawMetrics]) -> list[DongScores]:
    # 개수형 → 인구 대비 밀도(1만명당)
    def density(attr):
        return {r.code: getattr(r, attr) / r.population * 10000 for r in raws}

    cctv_d = density("cctv_cnt")
    conv_d = density("conv_cnt")
    mart_d = density("mart_cnt")
    hosp_d = density("hosp_cnt")
    bus_d = density("bus_cnt")
    park_d = density("park_cnt")
    crime = {r.code: r.crime_rate for r in raws}
    subway = {r.code: r.subway_access for r in raws}

    # 분위수 정규화
    cctv_s = _percentile_norm(cctv_d)
    conv_s = _percentile_norm(conv_d)
    mart_s = _percentile_norm(mart_d)
    hosp_s = _percentile_norm(hosp_d)
    bus_s = _percentile_norm(bus_d)
    park_s = _percentile_norm(park_d)
    crime_s = _percentile_norm(crime, invert=True)  # 범죄 낮을수록 좋음
    subway_s = _percentile_norm(subway)  # 접근성 높을수록 좋음

    by_code = {r.code: r for r in raws}
    result = []
    for code in by_code:
        result.append(DongScores(
            code=code,
            dong=by_code[code].dong,
            gu=by_code[code].gu,
            safety=round(0.5 * crime_s[code] + 0.5 * cctv_s[code], 4),
            convenience=round(
                0.4 * conv_s[code] + 0.3 * mart_s[code] + 0.3 * hosp_s[code], 4),
            mobility=round(0.5 * bus_s[code] + 0.5 * subway_s[code], 4),
            environment=round(park_s[code], 4),
            raw=by_code[code],
        ))
    return result


def rank(
    scores: list[DongScores],
    weights: dict[str, float],
    top_n: int = 5,
    extra_scores: dict[str, dict[str, float]] | None = None,
) -> list[Recommendation]:
    extra_scores = extra_scores or {}
    pool = scores
    scored = []
    for s in pool:
        contrib = {c: round(weights[c] * getattr(s, c), 4) for c in CATEGORIES}
        for cat, per_dong in extra_scores.items():
            contrib[cat] = round(weights.get(cat, 0.0) * per_dong.get(s.code, 0.0), 4)
        total = round(sum(contrib.values()), 4)
        scored.append((total, contrib, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        Recommendation(
            rank=i + 1, dong=s.dong, gu=s.gu,
            total_score=total, contributions=contrib, scores=s,
        )
        for i, (total, contrib, s) in enumerate(scored[:top_n])
    ]
