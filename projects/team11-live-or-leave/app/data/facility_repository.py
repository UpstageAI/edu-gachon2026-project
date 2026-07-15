"""
상가업소 저장소 — 사용자가 즉석에서 언급하는 임의 업종(버거·헬스장 등) 조회용.

기존 4개 카테고리(conv/mart/hosp 등)는 build_dong_metrics.py가 반경 1km
좌표검색으로 미리 집계해 dong_metrics.csv에 구워놓지만, 임의 업종은 사전에
뭘 물어볼지 모르니 미리 구울 수 없다. 그래서 원본 상가업소 CSV(약 54만 행)를
읽어 (자치구, 행정동, 업종소분류) 카운트로 집계해두고 즉석 조회한다.

주의: 반경검색이 아니라 원본 파일의 행정동명 컬럼 기준 집계다 (좌표 변환 불필요).
그래서 다른 4개 카테고리와 방법론이 다르다 — "반경 1km 내"가 아니라
"그 행정동에 속한" 업소 수. 이 차이는 explain 단계에서 각주로 알려야 한다.

로딩에 몇 초가 걸리므로(53만 행), 매 요청마다 새로 읽지 않도록
get_facility_repository()로 프로세스 수명 동안 캐시해 재사용한다.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

DEFAULT_CSV = (
    Path(__file__).resolve().parents[2] / "dataset" / "소상공인시장진흥공단_상가(상권)정보_서울.csv"
)


class FacilityRepository:
    def __init__(self, csv_path: str | Path = DEFAULT_CSV):
        self._counts: dict[tuple[str, str, str], int] = defaultdict(int)
        self._categories: set[str] = set()
        with open(csv_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                gu, dong, category = row["시군구명"], row["행정동명"], row["상권업종소분류명"]
                self._counts[(gu, dong, category)] += 1
                self._categories.add(category)

    def count(self, gu: str, dong: str, category: str) -> int:
        return self._counts.get((gu, dong, category), 0)

    def categories(self) -> set[str]:
        return set(self._categories)


_cache: FacilityRepository | None = None


def get_facility_repository() -> FacilityRepository:
    """프로세스 수명 동안 1회만 로딩해 재사용하는 지연 싱글턴."""
    global _cache
    if _cache is None:
        _cache = FacilityRepository()
    return _cache
