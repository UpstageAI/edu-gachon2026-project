"""
Kakao Local 키워드 검색 기반 시설 저장소 — 열린 키워드용.

FacilityRepository(상가 CSV)는 닫힌 집합(상권업종소분류 247개)만 다룬다.
CSV에 없는 임의 키워드(예: "클라이밍장", "도서관")는 Kakao Local API로
좌표를 받아 행정동 경계(point-in-polygon)에 매핑해 동별 카운트를 만든다.

흐름:
  키워드 → Kakao 키워드 검색(서울 bbox 타일링, 45건 초과 시 사분할 재귀)
        → 좌표 목록 → dong_boundaries.geojson PIP → {(구, 동): count}

호출량 관리:
  - 키워드당 최초 1회만 API를 때리고 결과를 디스크 캐시(JSON)로 저장.
    이후 동일 키워드는 0 call. TTL(기본 7일) 지나면 재조회.
  - Kakao 키워드 검색은 쿼리(rect)당 최대 45건까지만 노출되므로,
    total_count > 45면 rect를 사분할해 재귀한다. MAX_DEPTH로 폭주 차단 —
    한계 도달 시 그 타일은 45건까지만 세어진다(초고밀도 업종은 CSV 쪽을
    쓰는 하이브리드 전제라 실용상 문제없음).

테스트는 _fetch_page를 monkeypatch해 네트워크 없이 검증한다.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

from app.data.facility_repository import FacilityRepository, get_facility_repository

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GEOJSON = _ROOT / "dong_boundaries.geojson"
DEFAULT_CACHE_DIR = _ROOT / "dataset" / "kakao_cache"

KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
KAKAO_CATEGORY_URL = "https://dapi.kakao.com/v2/local/search/category.json"
# 서울 전체 bbox (lon_min, lat_min, lon_max, lat_max) — 타일링 시작점
SEOUL_RECT = (126.734, 37.413, 127.270, 37.715)
# 기준 장소(near 필터) 검색 전용 bbox — 서울보다 넓게 잡아 성남·과천·광명·
# 하남·구리·고양 등 수도권 위성도시도 기준 장소로 고를 수 있게 한다.
# (서울 동 데이터 자체는 여전히 서울만 있으니, 서울 밖 장소는 "거리 기준점"
# 으로만 쓰이고 그 장소가 속한 동이 추천 후보로 나오진 않는다.) 그 외
# 시설-카운트용 타일링(SEOUL_RECT)은 그대로 서울로 유지 — 넓히면 API 호출만
# 늘고 어차피 서울 동 경계 밖 좌표는 point-in-polygon에서 걸러진다.
PLACE_SEARCH_RECT = (126.60, 37.30, 127.35, 37.75)

# Kakao 표준 카테고리 그룹코드(14종 대분류) — 이 이름으로 요청되면 키워드 검색
# 대신 카테고리 검색을 쓴다. 키워드 추측(동의어 매핑) 없이 정확하고, 결과가
# 이미 거리순 정렬돼서 온다. 목록 밖 이름은 기존 키워드 검색으로 그대로 처리.
KAKAO_CATEGORY_CODE: dict[str, str] = {
    "대형마트": "MT1", "편의점": "CS2", "학교": "SC4", "학원": "AC5",
    "주차장": "PK6", "주유소": "OL7", "지하철역": "SW8", "은행": "BK9",
    "문화시설": "CT1", "관광명소": "AT4", "숙박": "AD5", "음식점": "FD6",
    "카페": "CE7", "병원": "HP8", "약국": "PM9",
}
PAGE_SIZE = 15
MAX_PAGE = 3          # Kakao는 rect당 최대 45건(15×3)까지만 노출
MAX_DEPTH = 6         # 사분할 재귀 한도 (4^6 = 최대 4096타일, 실제로는 밀도 높은 곳만 쪼개짐)
DEFAULT_TTL_SECONDS = 7 * 24 * 3600


class _DongIndex:
    """좌표 → (구, 동) 매핑. shapely STRtree로 426개 폴리곤을 인덱싱."""

    def __init__(self, geojson_path: str | Path = DEFAULT_GEOJSON):
        from shapely.geometry import shape
        from shapely.strtree import STRtree

        with open(geojson_path, encoding="utf-8") as f:
            gj = json.load(f)
        self._props = [ft["properties"] for ft in gj["features"]]
        self._polys = [shape(ft["geometry"]) for ft in gj["features"]]
        self._tree = STRtree(self._polys)

    def locate(self, lon: float, lat: float) -> tuple[str, str] | None:
        """좌표가 속한 (구, 동). 서울 경계 밖이면 None."""
        from shapely.geometry import Point

        pt = Point(lon, lat)
        for idx in self._tree.query(pt):
            if self._polys[idx].covers(pt):
                p = self._props[idx]
                return p["gu"], p["dong"]
        return None

    def centroids(self) -> dict[str, tuple[float, float]]:
        """행정동 코드 → 중심점 (lon, lat). 랜드마크 거리 필터용."""
        return {
            p["code"]: (poly.centroid.x, poly.centroid.y)
            for p, poly in zip(self._props, self._polys)
        }


class KakaoFacilityRepository:
    """열린 키워드 → 동별 업소 수. FacilityRepository와 동일한 count 인터페이스."""

    def __init__(
        self,
        api_key: str | None = None,
        cache_dir: str | Path = DEFAULT_CACHE_DIR,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        geojson_path: str | Path = DEFAULT_GEOJSON,
    ):
        self.api_key = api_key or os.environ.get("KAKAO_REST_API_KEY")
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_seconds
        self._geojson_path = geojson_path
        self._dong_index: _DongIndex | None = None  # 지연 로딩 (shapely import 비용)
        self._mem: dict[str, dict[tuple[str, str], int]] = {}
        self._candidates_mem: dict[str, list[dict]] = {}

    def available(self) -> bool:
        return bool(self.api_key)

    def count(self, gu: str, dong: str, category: str) -> int:
        return self.counts_for(category).get((gu, dong), 0)

    # ---- 키워드 → 동별 카운트 / 원본 장소 목록 (메모리 → 디스크 캐시 → API 순) ----

    def counts_for(self, keyword: str) -> dict[tuple[str, str], int]:
        return self._data_for(keyword)["counts"]

    def places_for(self, keyword: str) -> list[tuple[str, float, float]]:
        """API가 반환한 원본 장소 목록 [(장소명, lon, lat), ...] — 서울 행정동 안의
        것만. 개발자 검증·지도 핀 표시용. counts와 같은 디스크 캐시를 공유한다."""
        return [tuple(p) for p in self._data_for(keyword)["places"]]

    def _data_for(self, keyword: str) -> dict:
        keyword = keyword.strip()
        if keyword in self._mem:
            return self._mem[keyword]

        cached = self._load_cache(keyword)
        if cached is not None:
            self._mem[keyword] = cached
            return cached

        if not self.available():
            raise RuntimeError("KAKAO_REST_API_KEY 환경변수가 설정되지 않았습니다.")

        # 표준 카테고리(14종)면 카테고리 검색으로 — 키워드 추측 없이 정확하고
        # 거리순 정렬까지 온다. 캐시 키(디스크 파일명)는 그대로 사람이 부른
        # 이름 기준이라 호출부(HybridFacilityRepository 등)는 이 분기를 몰라도 된다.
        category_code = KAKAO_CATEGORY_CODE.get(keyword)
        found = self._search_all(keyword, category_code)
        counts: dict[tuple[str, str], int] = {}
        places: list[list] = []  # [장소명, lon, lat] — 서울 행정동 매핑된 것만
        index = self._get_dong_index()
        for name, lon, lat in found:
            loc = index.locate(lon, lat)
            if loc:
                counts[loc] = counts.get(loc, 0) + 1
                places.append([name, lon, lat])

        data = {"counts": counts, "places": places}
        self._save_cache(keyword, data)
        self._mem[keyword] = data
        return data

    # ---- 랜드마크 좌표 검색 ("서울대 근처" 류 거리 필터용) ----

    def search_place_candidates(self, name: str, limit: int = 5) -> list[dict]:
        """장소명으로 후보 여러 개를 찾는다 (Kakao 정확도순, 최대 limit개).

        "삼성" 같은 흔한 이름은 top-1이 사용자가 의도한 곳이 아닐 수 있다
        (회사명·주소 등 임의 장소를 받다 보니 동명이인 리스크가 큼) — top-1을
        말없이 믿는 대신 후보를 보여주고 사용자가 직접 고르게 하기 위한 API.
        각 후보: {"name": 상호명, "address": 도로명(없으면 지번) 주소,
        "lon": 경도, "lat": 위도}. 수도권 rect(PLACE_SEARCH_RECT)로 제한해
        동명 타지역 장소(예: 부산 서면역)가 섞이는 걸 막으면서도, 성남시 같은
        서울 인접 위성도시는 기준 장소로 검색할 수 있게 한다. API 1 call, 디스크 캐시."""
        name = name.strip()
        if name in self._candidates_mem:
            return self._candidates_mem[name][:limit]

        path = self._place_cache_path(name)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if (time.time() - data.get("fetched_at", 0) <= self.ttl_seconds
                    and "candidates" in data):  # 구버전 캐시(candidates 없음)는 재조회
                self._candidates_mem[name] = data["candidates"]
                return data["candidates"][:limit]
        except (OSError, json.JSONDecodeError, KeyError):
            pass

        if not self.available():
            raise RuntimeError("KAKAO_REST_API_KEY 환경변수가 설정되지 않았습니다.")

        docs = self._fetch_page(name, PLACE_SEARCH_RECT, page=1)["documents"]
        candidates = [
            {
                "name": d.get("place_name") or name,
                "address": d.get("road_address_name") or d.get("address_name") or "",
                "lon": float(d["x"]), "lat": float(d["y"]),
            }
            for d in docs
        ]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "name": name, "fetched_at": time.time(),
            "candidates": candidates,
        }, ensure_ascii=False), encoding="utf-8")
        self._candidates_mem[name] = candidates
        return candidates[:limit]

    def locate_place(self, name: str) -> tuple[float, float] | None:
        """대표 좌표 1개(Kakao 1위 결과)만 필요한 호출부용 하위호환 래퍼.

        새 코드는 후보를 보여주고 사용자가 고르게 하는
        search_place_candidates()를 직접 쓰는 걸 권장한다 — top-1을 그냥
        믿으면 "삼성" 같은 모호한 이름에서 엉뚱한 곳이 뽑힐 수 있다."""
        candidates = self.search_place_candidates(name, limit=1)
        return (candidates[0]["lon"], candidates[0]["lat"]) if candidates else None

    def _place_cache_path(self, name: str) -> Path:
        return self.cache_dir / ("place_" + name.encode("utf-8").hex() + ".json")

    def dong_centroids(self) -> dict[str, tuple[float, float]]:
        return self._get_dong_index().centroids()

    # ---- 디스크 캐시 ----

    def _cache_path(self, keyword: str) -> Path:
        # 키워드를 그대로 파일명에 쓰면 경로문자(/ 등)로 깨질 수 있어 hex 인코딩
        return self.cache_dir / (keyword.encode("utf-8").hex() + ".json")

    def _load_cache(self, keyword: str) -> dict | None:
        path = self._cache_path(keyword)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if time.time() - data.get("fetched_at", 0) > self.ttl_seconds:
            return None
        if "places" not in data:  # 구버전 캐시(원본 좌표 미저장) → 재조회
            return None
        return {
            "counts": {(gu, dong): n for gu, dong, n in data["counts"]},
            "places": data["places"],
        }

    def _save_cache(self, keyword: str, data: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "keyword": keyword,
            "fetched_at": time.time(),
            "counts": [[gu, dong, n] for (gu, dong), n in data["counts"].items()],
            "places": data["places"],
        }
        self._cache_path(keyword).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    # ---- Kakao API (rect 사분할 타일링) ----

    def _search_all(
        self, keyword: str, category_code: str | None = None
    ) -> list[tuple[str, float, float]]:
        """서울 bbox 전체에서 (장소명, 좌표) 전부 수집. 장소 id로 중복 제거.
        category_code가 있으면 카테고리 검색(정확·거리순), 없으면 키워드 검색."""
        seen: dict[str, tuple[str, float, float]] = {}
        self._search_rect(keyword, category_code, SEOUL_RECT, depth=0, seen=seen)
        return list(seen.values())

    def _search_rect(self, keyword, category_code, rect, depth, seen) -> None:
        docs, total = self._fetch_rect(keyword, category_code, rect)
        if total > MAX_PAGE * PAGE_SIZE and depth < MAX_DEPTH:
            for sub in _quad_split(rect):
                self._search_rect(keyword, category_code, sub, depth + 1, seen)
            return
        for d in docs:
            seen[d["id"]] = (d.get("place_name", ""), float(d["x"]), float(d["y"]))

    def _fetch_rect(self, keyword, category_code, rect) -> tuple[list[dict], int]:
        """rect 안에서 최대 45건 페이지네이션. (documents, total_count) 반환."""
        docs: list[dict] = []
        total = 0
        for page in range(1, MAX_PAGE + 1):
            body = self._fetch_page(keyword, rect, page, category_code)
            docs.extend(body["documents"])
            total = body["meta"]["total_count"]
            if body["meta"]["is_end"]:
                break
        return docs, total

    def _fetch_page(
        self, keyword: str, rect: tuple, page: int, category_code: str | None = None
    ) -> dict:
        """실제 HTTP 1회. 테스트에서 이 메서드만 monkeypatch하면 네트워크가 끊긴다.
        category_code가 있으면 카테고리 검색 엔드포인트, 없으면 키워드 검색."""
        import httpx

        url = KAKAO_CATEGORY_URL if category_code else KAKAO_KEYWORD_URL
        params = {
            "rect": f"{rect[0]},{rect[1]},{rect[2]},{rect[3]}",
            "page": page,
            "size": PAGE_SIZE,
        }
        params["category_group_code" if category_code else "query"] = (
            category_code or keyword
        )
        resp = httpx.get(
            url, headers={"Authorization": f"KakaoAK {self.api_key}"},
            params=params, timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()

    def _get_dong_index(self) -> _DongIndex:
        if self._dong_index is None:
            self._dong_index = _DongIndex(self._geojson_path)
        return self._dong_index


def _quad_split(rect: tuple) -> list[tuple]:
    lon_min, lat_min, lon_max, lat_max = rect
    lon_mid = (lon_min + lon_max) / 2
    lat_mid = (lat_min + lat_max) / 2
    return [
        (lon_min, lat_min, lon_mid, lat_mid),
        (lon_mid, lat_min, lon_max, lat_mid),
        (lon_min, lat_mid, lon_mid, lat_max),
        (lon_mid, lat_mid, lon_max, lat_max),
    ]


class HybridFacilityRepository:
    """CSV 우선, 미보유 키워드만 Kakao 폴백.

    - CSV에 있는 업종(닫힌 집합): 기존 FacilityRepository 그대로 — API 0 call
    - CSV에 없는 열린 키워드: KakaoFacilityRepository (키 없으면 resolvable=False)

    tools.py는 category 타입 FilterClause 중 resolvable하지 않은 항목을 필터에서
    빼고 결과에 unresolved로 표시한다 — 전 지역 실격(카운트 전부 0) 같은 조용한
    오동작을 막기 위함.
    """

    def __init__(
        self,
        csv_repo: FacilityRepository | None = None,
        kakao_repo: KakaoFacilityRepository | None = None,
    ):
        self._csv = csv_repo or get_facility_repository()
        self._kakao = kakao_repo or KakaoFacilityRepository()

    def categories(self) -> set[str]:
        return self._csv.categories()

    def resolvable(self, category: str) -> bool:
        return category in self._csv.categories() or self._kakao.available()

    def count(self, gu: str, dong: str, category: str) -> int:
        if category in self._csv.categories():
            return self._csv.count(gu, dong, category)
        return self._kakao.count(gu, dong, category)

    def places_for(self, category: str) -> list[tuple[str, float, float]] | None:
        """Kakao 경유 키워드의 원본 좌표 목록. CSV 출처 업종은 좌표가 없어 None."""
        if category in self._csv.categories():
            return None
        return self._kakao.places_for(category)

    # '근처' 거리 필터는 좌표가 필요해 CSV로는 불가 — 항상 Kakao 경유
    def near_resolvable(self) -> bool:
        return self._kakao.available()

    def locate_place(self, name: str) -> tuple[float, float] | None:
        return self._kakao.locate_place(name)

    def search_place_candidates(self, name: str, limit: int = 5) -> list[dict]:
        return self._kakao.search_place_candidates(name, limit=limit)

    def dong_centroids(self) -> dict[str, tuple[float, float]]:
        return self._kakao.dong_centroids()


_hybrid_cache: HybridFacilityRepository | None = None


def get_hybrid_facility_repository() -> HybridFacilityRepository:
    """프로세스 수명 동안 1회만 만들어 재사용 (CSV 로딩·dong 인덱스·메모리 캐시 공유)."""
    global _hybrid_cache
    if _hybrid_cache is None:
        _hybrid_cache = HybridFacilityRepository()
    return _hybrid_cache
