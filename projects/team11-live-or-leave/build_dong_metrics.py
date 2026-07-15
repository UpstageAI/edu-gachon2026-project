"""
행정동 424개 단위 지표 테이블 빌더.

분석 단위: 행정동 중심점 (상권분석 영역 데이터, EPSG:5181 TM 좌표).
거리 계산: 모든 좌표를 EPSG:5181(미터)로 통일 후 KDTree 반경 검색.

지표별 처리 정책 (앞선 논의 확정):
  - 반경 내 개수형 (반경 1km): 편의점·마트·병원·버스·CCTV·공원
      → 각 행정동 중심점 반경 내 시설 수, 생활인구로 나눠 밀도화
  - 최근접 거리형: 지하철역 → 가장 가까운 역까지 거리 + 거리감쇠
  - 구 값 상속: 범죄 → 행정동은 소속 자치구 범죄율을 그대로 물려받음
  - 행정동 고유값: 생활인구 (행정동코드 앞5자리로 자치구 판별용으로도 사용)

행정동 크기 중앙값 0.97km²(반지름 ~557m)라 반경 1km면 대부분 동을 덮어
중심점 근사의 오차가 작다.
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict

import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree

UP = "/mnt/user-data/uploads"
OUT = "/mnt/user-data/outputs/dong_metrics.csv"

RADIUS_M = 1000.0        # 반경 내 개수형 지표의 반경 (미터)
SUBWAY_DECAY_M = 500.0   # 지하철 거리감쇠 기준척도 (미터)

# 위경도(4326) → 서울 TM(5181, 미터) 변환기
to_tm = Transformer.from_crs("EPSG:4326", "EPSG:5181", always_xy=True)

GU_CODE = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구",
    "11215": "광진구", "11230": "동대문구", "11260": "중랑구", "11290": "성북구",
    "11305": "강북구", "11320": "도봉구", "11350": "노원구", "11380": "은평구",
    "11410": "서대문구", "11440": "마포구", "11470": "양천구", "11500": "강서구",
    "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구",
    "11740": "강동구",
}
GU_LIST = list(GU_CODE.values())


def _norm_gu(name: str) -> str | None:
    name = (name or "").strip()
    if name in GU_LIST:
        return name
    if name + "구" in GU_LIST:
        return name + "구"
    return None


# ---------- 행정동 중심점 (기준점) ----------

def load_dong_centers():
    """행정동 중심점 로드 → [(code, name, gu, tm_x, tm_y)]. 이미 TM(5181)."""
    dongs = []
    with open(f"{UP}/서울시_상권분석서비스_영역-행정동_.csv", encoding="cp949") as f:
        for row in csv.DictReader(f):
            code = row["행정동_코드"].strip()
            gu = GU_CODE.get(code[:5])
            if not gu:
                continue
            dongs.append({
                "code": code,
                "name": row["행정동_명"].strip(),
                "gu": gu,
                "x": float(row["엑스좌표_값"]),
                "y": float(row["와이좌표_값"]),
            })
    return dongs


# ---------- 시설 좌표 로더 (위경도 → TM) ----------

def _load_points_latlon(path, lon_key, lat_key, enc, filt=None):
    """위경도 CSV → TM 좌표 배열. filt(row)->bool로 업종 필터."""
    pts = []
    with open(f"{UP}/{path}", encoding=enc) as f:
        for row in csv.DictReader(f):
            if filt and not filt(row):
                continue
            try:
                lon, lat = float(row[lon_key]), float(row[lat_key])
            except (ValueError, KeyError):
                continue
            if not (124 < lon < 132 and 33 < lat < 39):  # 한국 범위 밖 제외
                continue
            x, y = to_tm.transform(lon, lat)
            pts.append((x, y))
    return np.array(pts) if pts else np.empty((0, 2))


def count_within_radius(centers_xy, facility_xy, radius=RADIUS_M):
    """각 중심점의 반경 내 시설 개수."""
    if len(facility_xy) == 0:
        return np.zeros(len(centers_xy), dtype=int)
    tree = cKDTree(facility_xy)
    return np.array([len(tree.query_ball_point(c, radius)) for c in centers_xy])


def nearest_distance(centers_xy, facility_xy):
    """각 중심점에서 가장 가까운 시설까지 거리(m)."""
    if len(facility_xy) == 0:
        return np.full(len(centers_xy), np.inf)
    tree = cKDTree(facility_xy)
    d, _ = tree.query(centers_xy, k=1)
    return d


# ---------- 영역 데이터 (구 상속 / 행정동 고유) ----------

def load_population():
    """생활인구: 동별 720레코드 평균 → 행정동코드별 값."""
    dong_sum = defaultdict(float)
    dong_cnt = defaultdict(int)
    with open(f"{UP}/LOCAL_PEOPLE_DONG_202606.csv", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            code = row["행정동코드"]
            dong_sum[code] += float(row["총생활인구수"])
            dong_cnt[code] += 1
    return {c: dong_sum[c] / dong_cnt[c] for c in dong_sum}


def load_gu_crime_rate(gu_pop):
    """자치구 범죄율(1만명당). 행정동이 상속받을 값."""
    crime = {}
    with open(f"{UP}/5대_범죄_발생현황_20260708232422.csv", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            gu = row["자치구"]
            if gu in GU_LIST:
                crime[gu] = int(float(row["2024 합계 소계 발생"]))
    # 자치구 인구 = 소속 행정동 생활인구 합
    return {gu: crime.get(gu, 0) / max(gu_pop.get(gu, 1), 1) * 10000 for gu in GU_LIST}


def main():
    print("행정동 중심점 로드...")
    dongs = load_dong_centers()
    centers = np.array([[d["x"], d["y"]] for d in dongs])
    print(f"  행정동 {len(dongs)}개")

    print("생활인구 집계...")
    pop_by_code = load_population()
    gu_pop = defaultdict(float)
    for code, p in pop_by_code.items():
        gu = GU_CODE.get(code[:5])
        if gu:
            gu_pop[gu] += p
    gu_crime_rate = load_gu_crime_rate(gu_pop)

    print("시설 좌표 로드 및 TM 변환...")
    conv = _load_points_latlon(
        "소상공인시장진흥공단_상가_상권_정보_서울_202603.csv", "경도", "위도", "utf-8-sig",
        filt=lambda r: r["상권업종소분류명"] == "편의점")
    mart = _load_points_latlon(
        "소상공인시장진흥공단_상가_상권_정보_서울_202603.csv", "경도", "위도", "utf-8-sig",
        filt=lambda r: r["상권업종소분류명"] == "슈퍼마켓")
    hosp = _load_points_latlon(
        "소상공인시장진흥공단_상가_상권_정보_서울_202603.csv", "경도", "위도", "utf-8-sig",
        filt=lambda r: r["상권업종중분류명"] == "병원")
    bus = _load_points_latlon(
        "서울시버스정류소위치정보_20260701_.csv", "X좌표", "Y좌표", "utf-8-sig")
    cctv = _load_points_latlon(
        "CCTV정보_서울특별시.csv", "WGS84경도", "WGS84위도", "utf-8-sig")
    park = _load_points_latlon(
        "서울시_도시공원정보표준데이터.csv", "경도", "위도", "utf-8-sig")
    subway = _load_points_latlon(
        "서울시_역사마스터_정보.csv", "경도", "위도", "utf-8-sig")

    print("  반경 내 개수 계산...")
    n_conv = count_within_radius(centers, conv)
    n_mart = count_within_radius(centers, mart)
    n_hosp = count_within_radius(centers, hosp)
    n_bus = count_within_radius(centers, bus)
    n_cctv = count_within_radius(centers, cctv)
    n_park = count_within_radius(centers, park)
    print("  지하철 최근접 거리...")
    d_subway = nearest_distance(centers, subway)

    print("저장...")
    fields = ["code", "dong", "gu", "population", "crime_rate",
              "conv_cnt", "mart_cnt", "hosp_cnt", "bus_cnt", "cctv_cnt",
              "park_cnt", "subway_dist_m", "subway_access"]
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(fields)
        for i, d in enumerate(dongs):
            pop = pop_by_code.get(d["code"], 0)
            dist = d_subway[i]
            access = math.exp(-dist / SUBWAY_DECAY_M) if math.isfinite(dist) else 0.0
            w.writerow([
                d["code"], d["name"], d["gu"], round(pop),
                round(gu_crime_rate[d["gu"]], 2),
                int(n_conv[i]), int(n_mart[i]), int(n_hosp[i]),
                int(n_bus[i]), int(n_cctv[i]), int(n_park[i]),
                round(dist, 1) if math.isfinite(dist) else -1,
                round(access, 4),
            ])
    print(f"완료: {OUT} ({len(dongs)}개 행정동)")
    return OUT


if __name__ == "__main__":
    main()
