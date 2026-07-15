"""도구 실행기 — 행정동 단위. 서비스 계층에 위임.

required_filters(FilterClause 목록)를 type별로 디스패치해 pool을 순서대로
좁혀나간다: near(그룹별 OR/AND) → gu. 새 필터 타입이 늘어도 여기 분기 하나 +
scoring.py 실행 함수 하나만 추가하면 된다.

near/gu는 이제 LLM이 자연어에서 추론하지 않는다 — 사용자가 UI에서 직접
고른 구조화 입력(구 멀티셀렉트, 기준 장소 텍스트)을 그대로 FilterClause로
만들어 넘긴다. "선택 요구사항에 잠깐 나온 단어가 하드필터로 오인식되는"
부류의 버그가 이 두 타입에서는 애초에 발생할 수 없다 — LLM이 이 값을
판단할 기회 자체가 없기 때문.

category(업종 존재)·require_large_hospital 하드필터는 제거됐다(과거엔 있었음):
①닫힌 집합 밖 업종은 Kakao 검색 커버리지가 들쭉날쭉해 "실제로는 있는데 없다고
실격" 오탐이 잦았고 검증이 어려웠음, ②대형병원 요구는 near(특정 대형병원 근처)
필터로 동일하게 해결 가능해 별도 특수 케이스를 유지할 이유가 없었음. 업종
언급은 이제 extra_categories(선택, 점수화)로만 다뤄진다.
"""
from __future__ import annotations

from app.data.csv_repository import CsvDongRepository
from app.data.kakao_facility_repository import get_hybrid_facility_repository
from app.schemas.tools import CompareTool, FilterClause, RecommendTool
from app.services import scoring

# '근처'의 기본 반경 (동 중심점 기준). FilterClause.radius_km로 절별 override 가능.
NEAR_RADIUS_KM = 3.0

SEOUL_GU = [
    "강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "구로구", "금천구",
    "노원구", "도봉구", "동대문구", "동작구", "마포구", "서대문구", "서초구", "성동구",
    "성북구", "송파구", "양천구", "영등포구", "용산구", "은평구", "종로구", "중구", "중랑구",
]

# "강남3구" 같은 통칭 → 실제 구 이름 목록. LLM은 통칭을 그대로 출력해도 되고,
# 코드가 여기서 해석한다(잘못된 구 이름 나열 방지).
GU_ALIASES: dict[str, list[str]] = {
    "강남3구": ["강남구", "서초구", "송파구"],
    "강남4구": ["강남구", "서초구", "송파구", "강동구"],
    "강북": ["강북구", "도봉구", "노원구", "성북구", "동대문구", "중랑구"],
    "도심권": ["종로구", "중구", "용산구"],
}

class ToolExecutor:
    def __init__(self, repo: CsvDongRepository):
        self.repo = repo

    def recommend(self, args: RecommendTool) -> dict:
        raws = self.repo.all_metrics()
        scores = scoring.score_dongs(raws)

        by_type: dict[str, list[FilterClause]] = {"near": [], "gu": []}
        for c in args.required_filters:
            by_type[c.type].append(c)

        # CSV 우선, CSV에 없는 열린 키워드만 Kakao 폴백. gu는 로컬
        # 데이터만으로 되므로 이것들만 있을 땐 Kakao 저장소 자체를 안 만든다.
        facility_repo = (
            get_hybrid_facility_repository()
            if args.extra_categories or by_type["near"]
            else None
        )

        extra_counts: dict[str, dict[str, int]] = {
            cat: {r.code: facility_repo.count(r.gu, r.dong, cat) for r in raws}
            for cat in args.extra_categories
        }
        extra_scores = scoring.score_extra_categories(raws, extra_counts)

        pool = scores
        disqualified: list[dict] = []
        unresolved_required: list[str] = []
        landmarks: dict[str, tuple[float, float]] = {}

        # --- near: 랜드마크 거리 필터. 같은 group명끼리는 OR, 나머지는 AND ---
        if by_type["near"]:
            groups: dict[object, list[FilterClause]] = {}
            for c in by_type["near"]:
                groups.setdefault(c.group or object(), []).append(c)

            for members in groups.values():
                resolved: list[tuple[FilterClause, tuple[float, float]]] = []
                for c in members:
                    # 좌표를 이미 알면(UI에서 후보 선택) 재검색하지 않는다 —
                    # 다시 검색하면 Kakao의 자체 1위 결과가 나와 사용자가
                    # 실제로 고른 후보와 달라질 수 있다.
                    if c.lon is not None and c.lat is not None:
                        coord = (c.lon, c.lat)
                    else:
                        coord = (facility_repo.locate_place(c.place)
                                 if facility_repo.near_resolvable() else None)
                    if coord:
                        landmarks[c.place] = coord
                        resolved.append((c, coord))
                    else:
                        unresolved_required.append(f"{c.place} 근처")
                if not resolved:
                    continue
                centroids = facility_repo.dong_centroids()
                if len(resolved) == 1:
                    (c, coord), = resolved
                    pool, near_disq = scoring.partition_by_proximity(
                        pool, {c.place: coord}, centroids, c.radius_km or NEAR_RADIUS_KM)
                    disqualified.extend(near_disq)
                else:
                    # OR — 그룹 내 하나라도 만족하면 통과
                    names = "/".join(c.place for c, _ in resolved)
                    new_pool, group_disq = [], []
                    for s in pool:
                        pt = centroids.get(s.code)
                        ok = pt is not None and any(
                            scoring.haversine_km(pt, coord) <= (c.radius_km or NEAR_RADIUS_KM)
                            for c, coord in resolved
                        )
                        (new_pool if ok else group_disq).append(s)
                    pool = new_pool
                    disqualified.extend(
                        {"scores": s, "missing": [f"{names} 중 근처 아님"]} for s in group_disq
                    )

        # --- gu: 행정구역 포함/제외 (API 불필요, 로컬 데이터만) ---
        for c in by_type["gu"]:
            resolved_gu = [g for name in (c.gu or []) for g in GU_ALIASES.get(name, [name])]
            label = "/".join(c.gu or [])
            new_pool, gu_disq = [], []
            for s in pool:
                ok = (s.gu in resolved_gu) != c.exclude
                (new_pool if ok else gu_disq).append(s)
            pool = new_pool
            reason = f"{label} 제외 대상" if c.exclude else f"{label} 안에 없음"
            disqualified.extend({"scores": s, "missing": [reason]} for s in gu_disq)

        weights = scoring.preference_to_weights(args.preference, args.extra_categories)
        recs = scoring.rank(pool, weights, top_n=args.top_n,
                            extra_scores=extra_scores)

        rec_dicts = [r.model_dump() for r in recs]
        if extra_counts:
            for rec_dict, rec in zip(rec_dicts, recs):
                rec_dict["extra_facilities"] = {
                    cat: extra_counts[cat].get(rec.scores.code, 0) for cat in extra_counts
                }

        result = {"weights": weights, "recommendations": rec_dicts}

        # 지도 핀용 좌표 — 사용자가 근처 필터 근거(기준 장소)를 눈으로 검증할 수 있게.
        # gu는 좌표가 없어 핀 없음.
        map_points = [
            {"label": name, "lon": lon, "lat": lat, "kind": "landmark"}
            for name, (lon, lat) in landmarks.items()
        ]
        if map_points:
            result["map_points"] = map_points

        if unresolved_required:
            result["unresolved_requirements"] = unresolved_required
        if disqualified:
            result["disqualified"] = [
                {"code": d["scores"].code, "gu": d["scores"].gu,
                 "dong": d["scores"].dong, "missing": d["missing"]}
                for d in disqualified
            ]
        return result

    def compare(self, args: CompareTool) -> dict:
        a, b = self.repo.get(args.gu_a), self.repo.get(args.gu_b)
        if not a or not b:
            return {"error": "존재하지 않는 행정동"}
        return {"a": a.model_dump(), "b": b.model_dump()}
