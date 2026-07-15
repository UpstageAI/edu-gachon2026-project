"""
행정동 경계 GeoJSON 생성 — UI 지도용.

space_info/BND_ADM_DONG_PG.shp(전국 3559개 행정동 경계)를 서울 424~425개로 필터링해
dong_metrics.csv의 code/gu/dong을 속성으로 붙인 GeoJSON을 만든다. UI는 score 데이터를
"code" 하나로 이 GeoJSON에 조인하면 된다.

세 가지 알려진 예외를 처리한다 (근거는 세션에서 원본 데이터 직접 대조로 확인됨):
  - 7개 병합행정동 이름의 "?" — 서울시 상권분석서비스 원본 자체의 인코딩 손실.
    shapefile의 정확한 "·" 철자로 교체한다.
  - 강동구 상일동 — shapefile엔 상일1동/상일2동으로 분리돼 있어, 두 폴리곤 모두에
    같은 code를 단다.
  - 강남구 일원2동 — 2023년 행정구역 개편으로 개포3동에 편입됐다(통계청 SGIS 코드표
    확인: 2022년까지 일원2동 존재, 2023년 6월부터 일원2동 사라지고 개포3동 재등장).
    일원2동의 code를 개포3동 폴리곤에 단다.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pyproj
import shapefile
from shapely.geometry import mapping, shape

PROJECT_ROOT = Path(__file__).resolve().parent
SHP_PATH = PROJECT_ROOT / "space_info" / "BND_ADM_DONG_PG.shp"
PRJ_PATH = PROJECT_ROOT / "space_info" / "BND_ADM_DONG_PG.prj"
CODE_TABLE_PATH = PROJECT_ROOT / "space_info" / "센서스 공간정보 지역 코드.xlsx"
DONG_METRICS_PATH = PROJECT_ROOT / "dong_metrics.csv"
OUTPUT_PATH = PROJECT_ROOT / "dong_boundaries.geojson"

# 배포 시 매 렌더링마다 이 GeoJSON 전체가 브라우저로 전송·재렌더링되므로,
# 원본(평균 481점/폴리곤)을 그대로 쓰면 느리다. 좌표계가 미터 단위(TM)일 때
# 단순화해야 허용오차(m)를 직관적으로 잡을 수 있어 재투영 전에 수행한다.
SIMPLIFY_TOLERANCE_M = 15.0

# 서울시 상권분석서비스 원본 데이터 자체의 인코딩 손실("?") 보정 — shapefile의
# 정확한 철자로 교체한다 (우리 파이프라인 버그가 아니라 원본 배포 시점의 손실).
NAME_FIXES = {
    "상계3?4동": "상계3·4동",
    "상계6?7동": "상계6·7동",
    "중계2?3동": "중계2·3동",
    "금호2?3가동": "금호2·3가동",
    "종로1?2?3?4가동": "종로1·2·3·4가동",
    "종로5?6가동": "종로5·6가동",
    "면목3?8동": "면목3·8동",
}

# (구, dong_metrics.csv 동이름) -> shapefile에서 실제로 찾아야 할 (구, 동이름) 목록.
# 1:1이 아니면 여러 폴리곤 전부에 같은 code/속성을 단다.
NAME_OVERRIDES = {
    ("강동구", "상일동"): [("강동구", "상일1동"), ("강동구", "상일2동")],
    ("강남구", "일원2동"): [("강남구", "개포3동")],  # 2023년 개편으로 개포3동에 편입
}


def load_gu_map() -> dict[str, str]:
    """shapefile ADM_CD 앞 5자리 -> 자치구명. 최신 코드표(2025년 6월 시트) 기준."""
    df = pd.read_excel(CODE_TABLE_PATH, sheet_name="2025년 6월", header=1)
    df.columns = ["sido_cd", "sido_nm", "sgg_cd", "sgg_nm", "dong_cd", "dong_nm"]
    df = df.dropna(subset=["sido_cd"])
    prefix = df["sido_cd"].astype(str).str.strip() + df["sgg_cd"].astype(str).str.zfill(3)
    return dict(zip(prefix, df["sgg_nm"]))


def load_dong_rows() -> list[dict]:
    rows = []
    with open(DONG_METRICS_PATH, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            dong = NAME_FIXES.get(row["dong"], row["dong"])
            rows.append({"code": row["code"], "gu": row["gu"], "dong": dong})
    return rows


def simplify_geometry(geo: dict, tolerance: float) -> dict:
    """TM(미터) 좌표 상태에서 Douglas-Peucker 단순화. 위상(구멍 등)은 보존한다."""
    simplified = shape(geo).simplify(tolerance, preserve_topology=True)
    return mapping(simplified)


def reproject_geometry(geo: dict, transformer: pyproj.Transformer) -> dict:
    def reproject_ring(ring):
        return [[round(x, 6), round(y, 6)] for x, y in
                (transformer.transform(px, py) for px, py in ring)]

    if geo["type"] == "Polygon":
        coords = [reproject_ring(ring) for ring in geo["coordinates"]]
    elif geo["type"] == "MultiPolygon":
        coords = [[reproject_ring(ring) for ring in poly] for poly in geo["coordinates"]]
    else:
        raise ValueError(f"예상치 못한 geometry 타입: {geo['type']}")
    return {"type": geo["type"], "coordinates": coords}


def main():
    gu_map = load_gu_map()
    rows = load_dong_rows()

    # (구, shapefile에서 찾을 동이름) -> dong_metrics 행 목록
    lookup: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        targets = NAME_OVERRIDES.get((r["gu"], r["dong"]), [(r["gu"], r["dong"])])
        for gu, dong in targets:
            lookup.setdefault((gu, dong), []).append(r)

    to_wgs84 = pyproj.Transformer.from_crs(
        pyproj.CRS.from_wkt(PRJ_PATH.read_text(encoding="utf-8")),
        pyproj.CRS.from_epsg(4326),
        always_xy=True,
    )

    sf = shapefile.Reader(str(SHP_PATH), encoding="cp949")
    features = []
    matched_codes: set[str] = set()
    for sr in sf.iterShapeRecords():
        cd = sr.record["ADM_CD"]
        gu = gu_map.get(cd[:5])
        key = (gu, sr.record["ADM_NM"])
        if key not in lookup:
            continue
        geo = simplify_geometry(sr.shape.__geo_interface__, SIMPLIFY_TOLERANCE_M)
        geo = reproject_geometry(geo, to_wgs84)
        for r in lookup[key]:
            features.append({
                "type": "Feature",
                "properties": {"code": r["code"], "gu": r["gu"], "dong": r["dong"]},
                "geometry": geo,
            })
            matched_codes.add(r["code"])

    all_codes = {r["code"] for r in rows}
    missing = sorted(all_codes - matched_codes)
    by_code = {r["code"]: r for r in rows}
    print(f"매칭 {len(matched_codes)}/{len(all_codes)}개")
    for code in missing:
        r = by_code[code]
        print(f"  누락: {r['gu']} {r['dong']} (code={code})")

    fc = {"type": "FeatureCollection", "features": features}
    OUTPUT_PATH.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")

    def _count_points(geo):
        coords = geo["coordinates"]
        if geo["type"] == "Polygon":
            return sum(len(ring) for ring in coords)
        return sum(len(ring) for poly in coords for ring in poly)

    total_points = sum(_count_points(f["geometry"]) for f in features)
    print(f"완료: {OUTPUT_PATH} ({len(features)}개 피처, "
          f"좌표점 {total_points}개(평균 {total_points / len(features):.0f}), "
          f"{OUTPUT_PATH.stat().st_size / 1024 / 1024:.1f}MB)")


if __name__ == "__main__":
    main()
