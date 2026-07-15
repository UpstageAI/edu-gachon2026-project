"""kakao_facility_repository.py 단위 테스트 — 전부 네트워크 없이.

_fetch_page(HTTP 1회 지점)만 monkeypatch하면 그 위의 모든 로직(타일 사분할,
페이지네이션, PIP 매핑, 디스크 캐시, 하이브리드 폴백)이 실 API 없이 검증된다.

관점:
  - 좌표→행정동 매핑(PIP) 정확성 (경계 밖 좌표 무시 포함)
  - 45건 초과 시 rect 사분할 재귀
  - 디스크 캐시 적중(0 call)·TTL 만료 재조회
  - 키 없음 → available()=False, 조회 시 RuntimeError
  - 하이브리드: CSV 우선 / 미보유 키워드만 Kakao / resolvable 판정
  - tools 배선: 해석 불가 필수 업종은 필터 제외 + unresolved_requirements 보고
"""
from __future__ import annotations

import json

import pytest

from app.data.kakao_facility_repository import (
    KAKAO_CATEGORY_CODE,
    KAKAO_CATEGORY_URL,
    KAKAO_KEYWORD_URL,
    SEOUL_RECT,
    HybridFacilityRepository,
    KakaoFacilityRepository,
    _quad_split,
)


# ---------- 합성 지오메트리: 정사각형 동 2개 ----------

@pytest.fixture
def square_geojson(tmp_path):
    """A동 = lon 0~1 × lat 0~1, B동 = lon 1~2 × lat 0~1."""
    def sq(lon0, lat0, lon1, lat1):
        return {"type": "Polygon", "coordinates": [[
            [lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]}

    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"code": "A1", "gu": "가구", "dong": "A동"},
         "geometry": sq(0, 0, 1, 1)},
        {"type": "Feature", "properties": {"code": "B1", "gu": "나구", "dong": "B동"},
         "geometry": sq(1, 0, 2, 1)},
    ]}
    path = tmp_path / "squares.geojson"
    path.write_text(json.dumps(gj), encoding="utf-8")
    return path


def _repo(tmp_path, square_geojson, **kw) -> KakaoFacilityRepository:
    return KakaoFacilityRepository(
        api_key=kw.pop("api_key", "test-kakao-key"),
        cache_dir=tmp_path / "cache",
        geojson_path=square_geojson,
        **kw,
    )


def _page(docs, total, is_end=True):
    return {"documents": docs, "meta": {"total_count": total, "is_end": is_end}}


def _doc(place_id, lon, lat, address=""):
    return {"id": place_id, "place_name": place_id, "x": str(lon), "y": str(lat),
            "road_address_name": address}


# ---------- 좌표 → 동 매핑 (PIP) ----------

def test_counts_for_maps_coordinates_to_dongs(tmp_path, square_geojson, monkeypatch):
    docs = [
        _doc("p1", 0.5, 0.5),   # A동
        _doc("p2", 0.2, 0.8),   # A동
        _doc("p3", 1.5, 0.5),   # B동
        _doc("p4", 9.0, 9.0),   # 경계 밖 → 무시
    ]
    monkeypatch.setattr(KakaoFacilityRepository, "_fetch_page",
                        lambda self, kw, rect, page, category_code=None: _page(docs, total=4))
    repo = _repo(tmp_path, square_geojson)

    assert repo.count("가구", "A동", "클라이밍장") == 2
    assert repo.count("나구", "B동", "클라이밍장") == 1
    assert repo.count("가구", "없는동", "클라이밍장") == 0


def test_duplicate_place_ids_across_pages_counted_once(tmp_path, square_geojson, monkeypatch):
    """rect 경계에 걸친 장소가 여러 타일에서 중복 반환돼도 id로 1번만 센다."""
    monkeypatch.setattr(
        KakaoFacilityRepository, "_fetch_page",
        lambda self, kw, rect, page, category_code=None: _page([_doc("same", 0.5, 0.5), _doc("same", 0.5, 0.5)], total=2))
    repo = _repo(tmp_path, square_geojson)
    assert repo.count("가구", "A동", "헬스장") == 1


# ---------- Kakao 표준 카테고리(14종) — 키워드 추측 없이 카테고리 검색 ----------
# _fetch_page 자체가 아니라 그 안의 httpx.get 호출을 가로채서, 실제로 어느
# 엔드포인트·파라미터로 나가는지(카테고리 vs 키워드) 검증한다.

def _fake_httpx_get(captured, empty_response):
    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"], captured["params"] = url, params
        return empty_response
    return fake_get


class _EmptyResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"documents": [], "meta": {"total_count": 0, "is_end": True}}


def test_known_category_name_uses_category_endpoint(tmp_path, square_geojson, monkeypatch):
    captured = {}
    monkeypatch.setattr("httpx.get", _fake_httpx_get(captured, _EmptyResp()))
    _repo(tmp_path, square_geojson).counts_for("약국")

    assert captured["url"] == KAKAO_CATEGORY_URL
    assert captured["params"]["category_group_code"] == KAKAO_CATEGORY_CODE["약국"] == "PM9"
    assert "query" not in captured["params"]


def test_unknown_keyword_uses_keyword_endpoint(tmp_path, square_geojson, monkeypatch):
    captured = {}
    monkeypatch.setattr("httpx.get", _fake_httpx_get(captured, _EmptyResp()))
    _repo(tmp_path, square_geojson).counts_for("클라이밍")

    assert captured["url"] == KAKAO_KEYWORD_URL
    assert captured["params"]["query"] == "클라이밍"
    assert "category_group_code" not in captured["params"]


# ---------- places_for: 원본 좌표 로컬 저장 (개발자 검증·지도 핀용) ----------

def test_places_for_returns_seoul_places_with_names(tmp_path, square_geojson, monkeypatch):
    docs = [_doc("암장A", 0.5, 0.5), _doc("암장B", 1.5, 0.5), _doc("타지역", 9.0, 9.0)]
    monkeypatch.setattr(KakaoFacilityRepository, "_fetch_page",
                        lambda self, kw, rect, page, category_code=None: _page(docs, total=3))
    repo = _repo(tmp_path, square_geojson)
    places = repo.places_for("클라이밍")
    assert ("암장A", 0.5, 0.5) in places and ("암장B", 1.5, 0.5) in places
    assert len(places) == 2  # 서울(합성 geojson) 밖은 저장 안 함


def test_places_survive_disk_cache_roundtrip(tmp_path, square_geojson, monkeypatch):
    calls = {"n": 0}

    def fake_fetch(self, kw, rect, page, category_code=None):
        calls["n"] += 1
        return _page([_doc("암장A", 0.5, 0.5)], total=1)

    monkeypatch.setattr(KakaoFacilityRepository, "_fetch_page", fake_fetch)
    _repo(tmp_path, square_geojson).places_for("클라이밍")
    n = calls["n"]
    # 새 인스턴스 → 디스크 캐시에서 원본 좌표까지 복원, 추가 call 없음
    assert _repo(tmp_path, square_geojson).places_for("클라이밍") == [("암장A", 0.5, 0.5)]
    assert calls["n"] == n


def test_legacy_cache_without_places_is_refetched(tmp_path, square_geojson, monkeypatch):
    """구버전 캐시(counts만 있고 places 없음)는 miss로 취급해 재조회한다."""
    import json as _json
    import time as _time

    repo = _repo(tmp_path, square_geojson)
    legacy = {"keyword": "헬스장", "fetched_at": _time.time(),
              "counts": [["가구", "A동", 1]]}  # places 키 없음
    repo.cache_dir.mkdir(parents=True, exist_ok=True)
    repo._cache_path("헬스장").write_text(_json.dumps(legacy), encoding="utf-8")

    monkeypatch.setattr(KakaoFacilityRepository, "_fetch_page",
                        lambda self, kw, rect, page, category_code=None: _page([_doc("짐A", 0.5, 0.5)], total=1))
    assert repo.places_for("헬스장") == [("짐A", 0.5, 0.5)]


# ---------- 45건 초과 → 사분할 재귀 ----------

def test_search_splits_rect_when_total_exceeds_cap(tmp_path, square_geojson, monkeypatch):
    fetched_rects = []

    def fake_fetch(self, kw, rect, page, category_code=None):
        fetched_rects.append(rect)
        if rect == SEOUL_RECT:
            return _page([], total=100)          # 루트: 45 초과 → 쪼개야 함
        return _page([_doc(f"p{len(fetched_rects)}", 0.5, 0.5)], total=1)

    monkeypatch.setattr(KakaoFacilityRepository, "_fetch_page", fake_fetch)
    repo = _repo(tmp_path, square_geojson)
    repo.counts_for("편의점")

    assert fetched_rects[0] == SEOUL_RECT
    assert len(fetched_rects) == 1 + 4  # 루트 1 + 사분할 4 (각각 total=1이라 더 안 쪼갬)
    assert set(fetched_rects[1:]) == set(_quad_split(SEOUL_RECT))


def test_quad_split_covers_parent_rect():
    subs = _quad_split((0, 0, 2, 2))
    assert len(subs) == 4
    assert (0, 0, 1, 1) in subs and (1, 1, 2, 2) in subs


# ---------- 디스크 캐시 ----------

def test_second_call_hits_disk_cache_without_api(tmp_path, square_geojson, monkeypatch):
    calls = {"n": 0}

    def fake_fetch(self, kw, rect, page, category_code=None):
        calls["n"] += 1
        return _page([_doc("p1", 0.5, 0.5)], total=1)

    monkeypatch.setattr(KakaoFacilityRepository, "_fetch_page", fake_fetch)
    _repo(tmp_path, square_geojson).counts_for("도서관")
    n_after_first = calls["n"]

    # 새 인스턴스(메모리 캐시 없음)라도 디스크 캐시로 0 call이어야 한다
    fresh = _repo(tmp_path, square_geojson)
    assert fresh.count("가구", "A동", "도서관") == 1
    assert calls["n"] == n_after_first


def test_expired_cache_triggers_refetch(tmp_path, square_geojson, monkeypatch):
    calls = {"n": 0}

    def fake_fetch(self, kw, rect, page, category_code=None):
        calls["n"] += 1
        return _page([_doc("p1", 0.5, 0.5)], total=1)

    monkeypatch.setattr(KakaoFacilityRepository, "_fetch_page", fake_fetch)
    _repo(tmp_path, square_geojson).counts_for("도서관")
    n_after_first = calls["n"]

    # ttl=0은 저장·재조회가 같은 clock tick에 일어나면 diff==0 > 0이 거짓이라 flaky.
    # 음수 TTL로 '항상 만료'를 보장한다.
    expired = _repo(tmp_path, square_geojson, ttl_seconds=-1)
    expired.counts_for("도서관")
    assert calls["n"] > n_after_first


# ---------- 키 없음 ----------

def test_unavailable_without_api_key(tmp_path, square_geojson):
    repo = _repo(tmp_path, square_geojson, api_key=None)
    assert repo.available() is False
    with pytest.raises(RuntimeError):
        repo.counts_for("클라이밍장")


# ---------- 하이브리드 ----------

class _FakeCsvRepo:
    def categories(self):
        return {"헬스장"}

    def count(self, gu, dong, category):
        return 7  # CSV 경로임을 식별할 수 있는 고정값


class _FakeKakaoRepo:
    def __init__(self, key=True):
        self._key = key

    def available(self):
        return self._key

    def count(self, gu, dong, category):
        return 3  # Kakao 경로 식별값


def test_hybrid_prefers_csv_for_known_categories():
    hybrid = HybridFacilityRepository(csv_repo=_FakeCsvRepo(), kakao_repo=_FakeKakaoRepo())
    assert hybrid.count("가구", "A동", "헬스장") == 7      # CSV에 있음 → CSV
    assert hybrid.count("가구", "A동", "클라이밍장") == 3  # CSV에 없음 → Kakao


def test_hybrid_resolvable_depends_on_csv_membership_and_key():
    with_key = HybridFacilityRepository(csv_repo=_FakeCsvRepo(), kakao_repo=_FakeKakaoRepo(key=True))
    no_key = HybridFacilityRepository(csv_repo=_FakeCsvRepo(), kakao_repo=_FakeKakaoRepo(key=False))
    assert with_key.resolvable("클라이밍장") is True
    assert no_key.resolvable("헬스장") is True       # CSV에 있으면 키 없어도 됨
    assert no_key.resolvable("클라이밍장") is False  # CSV에 없고 키도 없음


# ---------- locate_place: 랜드마크 좌표 1개 ('근처' 필터용) ----------

def test_locate_place_returns_first_result_coordinate(tmp_path, square_geojson, monkeypatch):
    monkeypatch.setattr(
        KakaoFacilityRepository, "_fetch_page",
        lambda self, kw, rect, page, category_code=None: _page([_doc("univ", 126.95, 37.46), _doc("noise", 127.0, 37.5)], total=2))
    repo = _repo(tmp_path, square_geojson)
    assert repo.locate_place("서울대") == (126.95, 37.46)


# ---------- search_place_candidates: 후보 여러 개 (오분류 방지 UX용) ----------

def test_search_place_candidates_returns_name_address_coords(tmp_path, square_geojson, monkeypatch):
    monkeypatch.setattr(
        KakaoFacilityRepository, "_fetch_page",
        lambda self, kw, rect, page, category_code=None: _page([
            _doc("삼성전자 강남", 127.02, 37.50, address="서울 강남구 테헤란로 1"),
            _doc("삼성디지털시티", 127.10, 37.25, address="경기 수원시 영통구 2"),
        ], total=2))
    repo = _repo(tmp_path, square_geojson)
    candidates = repo.search_place_candidates("삼성")
    assert candidates == [
        {"name": "삼성전자 강남", "address": "서울 강남구 테헤란로 1", "lon": 127.02, "lat": 37.50},
        {"name": "삼성디지털시티", "address": "경기 수원시 영통구 2", "lon": 127.10, "lat": 37.25},
    ]


def test_search_place_candidates_respects_limit(tmp_path, square_geojson, monkeypatch):
    monkeypatch.setattr(
        KakaoFacilityRepository, "_fetch_page",
        lambda self, kw, rect, page, category_code=None: _page(
            [_doc(f"장소{i}", 127.0 + i * 0.01, 37.5) for i in range(10)], total=10))
    repo = _repo(tmp_path, square_geojson)
    assert len(repo.search_place_candidates("장소", limit=3)) == 3


def test_locate_place_uses_first_candidate(tmp_path, square_geojson, monkeypatch):
    """locate_place는 search_place_candidates의 1등 좌표만 쓰는 하위호환 래퍼."""
    monkeypatch.setattr(
        KakaoFacilityRepository, "_fetch_page",
        lambda self, kw, rect, page, category_code=None: _page([
            _doc("univ", 126.95, 37.46), _doc("noise", 127.0, 37.5)], total=2))
    repo = _repo(tmp_path, square_geojson)
    assert repo.locate_place("서울대") == (126.95, 37.46)
    assert repo.search_place_candidates("서울대")[0]["name"] == "univ"


def test_search_place_candidates_caches_across_instances(tmp_path, square_geojson, monkeypatch):
    calls = {"n": 0}

    def fake_fetch(self, kw, rect, page, category_code=None):
        calls["n"] += 1
        return _page([_doc("univ", 126.95, 37.46)], total=1)

    monkeypatch.setattr(KakaoFacilityRepository, "_fetch_page", fake_fetch)
    _repo(tmp_path, square_geojson).search_place_candidates("서울대")
    n = calls["n"]
    # 새 인스턴스라도 디스크 캐시 재사용 — 재조회 0 call
    assert _repo(tmp_path, square_geojson).search_place_candidates("서울대")[0]["name"] == "univ"
    assert calls["n"] == n


def test_locate_place_caches_including_not_found(tmp_path, square_geojson, monkeypatch):
    calls = {"n": 0}

    def fake_fetch(self, kw, rect, page, category_code=None):
        calls["n"] += 1
        return _page([], total=0)

    monkeypatch.setattr(KakaoFacilityRepository, "_fetch_page", fake_fetch)
    assert _repo(tmp_path, square_geojson).locate_place("존재안함") is None
    # 새 인스턴스라도 디스크 캐시로 '없음'까지 재사용 — 재조회 0 call
    assert _repo(tmp_path, square_geojson).locate_place("존재안함") is None
    assert calls["n"] == 1


# ---------- partition_by_proximity (scoring) ----------

def test_partition_by_proximity_filters_by_distance():
    from app.services.scoring import haversine_km, partition_by_proximity

    class _S:  # DongScores에서 필요한 건 code뿐
        def __init__(self, code):
            self.code = code

    # 서울시청(126.978, 37.566) 기준: A=시청 바로 옆, B=수원(~34km)
    landmarks = {"시청": (126.978, 37.566)}
    centroids = {"A": (126.980, 37.567), "B": (127.028, 37.263)}
    qualified, disqualified = partition_by_proximity(
        [_S("A"), _S("B")], landmarks, centroids, radius_km=3.0)

    assert [s.code for s in qualified] == ["A"]
    assert disqualified[0]["scores"].code == "B"
    assert "시청 근처(3km 이내) 아님" in disqualified[0]["missing"]
    assert haversine_km(centroids["A"], landmarks["시청"]) < 1.0  # 좌표 검증


def test_partition_by_proximity_disqualifies_unknown_centroid():
    """geojson에 없는 code(중심점 불명)는 보수적으로 실격 — 조용히 통과 금지."""
    from app.services.scoring import partition_by_proximity

    class _S:
        code = "유령동"

    qualified, disqualified = partition_by_proximity(
        [_S()], {"시청": (126.978, 37.566)}, {}, radius_km=3.0)
    assert not qualified and len(disqualified) == 1


# ---------- tools 배선: '근처' 거리 필터 ----------

class _FakeNearHybrid:
    """conftest.sample_raws의 A동(강남구)만 반경 안에 들도록 설계된 대역.
    sample_raws의 code: A1/B1/C1."""

    def __init__(self, key=True):
        self._key = key

    def categories(self):
        return set()

    def resolvable(self, category):
        return True

    def count(self, gu, dong, category):
        return 1

    def near_resolvable(self):
        return self._key

    def locate_place(self, name):
        return (127.00, 37.50) if name == "서울대" else None

    def dong_centroids(self):
        return {"A1": (127.00, 37.505),  # 랜드마크에서 ~0.6km (반경 안)
                "B1": (127.10, 37.60),   # ~13km
                "C1": (126.90, 37.40)}   # ~14km


def test_recommend_applies_near_filter_and_reports_reason(monkeypatch, sample_raws):
    from app.agent import tools as tools_mod
    from app.schemas.tools import CategoryPreference, FilterClause, Importance, RecommendTool
    from tests.conftest import FakeRepo

    monkeypatch.setattr(tools_mod, "get_hybrid_facility_repository", lambda: _FakeNearHybrid())
    result = tools_mod.ToolExecutor(FakeRepo(sample_raws)).recommend(RecommendTool(
        preference=CategoryPreference(
            safety=Importance.HIGH, convenience=Importance.NONE,
            mobility=Importance.NONE, environment=Importance.NONE),
        required_filters=[FilterClause(type="near", place="서울대")], top_n=3,
    ))

    assert [r["dong"] for r in result["recommendations"]] == ["A동"]
    assert len(result["disqualified"]) == 2
    from app.agent.tools import NEAR_RADIUS_KM
    expected = f"서울대 근처({NEAR_RADIUS_KM:g}km 이내) 아님"
    assert all(expected in d["missing"] for d in result["disqualified"])
    # 기준 장소 핀이 지도용 좌표로 실려야 함 (UI 검증용)
    assert result["map_points"] == [
        {"label": "서울대", "lon": 127.00, "lat": 37.50, "kind": "landmark"}
    ]


def test_recommend_reports_unresolved_when_landmark_not_found(monkeypatch, sample_raws):
    """좌표를 못 찾은 랜드마크는 전 지역 실격 대신 unresolved로 보고하고 필터 생략."""
    from app.agent import tools as tools_mod
    from app.schemas.tools import CategoryPreference, FilterClause, Importance, RecommendTool
    from tests.conftest import FakeRepo

    monkeypatch.setattr(tools_mod, "get_hybrid_facility_repository", lambda: _FakeNearHybrid())
    result = tools_mod.ToolExecutor(FakeRepo(sample_raws)).recommend(RecommendTool(
        preference=CategoryPreference(
            safety=Importance.HIGH, convenience=Importance.NONE,
            mobility=Importance.NONE, environment=Importance.NONE),
        required_filters=[FilterClause(type="near", place="존재안하는곳")], top_n=3,
    ))

    assert result["unresolved_requirements"] == ["존재안하는곳 근처"]
    assert len(result["recommendations"]) == 3  # 필터 미적용
    assert "disqualified" not in result


# ---------- tools 배선: near OR그룹 ----------

class _FakeMultiNearHybrid:
    """두 랜드마크 — 강남역은 A동 근처, 홍대입구역은 C동 근처. B동은 둘 다 아님."""

    def resolvable(self, category):
        return True

    def near_resolvable(self):
        return True

    def locate_place(self, name):
        return {"강남역": (127.00, 37.50), "홍대입구역": (126.90, 37.40)}.get(name)

    def dong_centroids(self):
        return {"A1": (127.00, 37.505), "B1": (127.10, 37.60), "C1": (126.905, 37.405)}


def test_recommend_near_or_group_passes_if_any_landmark_matches(monkeypatch, sample_raws):
    from app.agent import tools as tools_mod
    from app.schemas.tools import CategoryPreference, FilterClause, Importance, RecommendTool
    from tests.conftest import FakeRepo

    monkeypatch.setattr(tools_mod, "get_hybrid_facility_repository", lambda: _FakeMultiNearHybrid())
    result = tools_mod.ToolExecutor(FakeRepo(sample_raws)).recommend(RecommendTool(
        preference=CategoryPreference(
            safety=Importance.NONE, convenience=Importance.NONE,
            mobility=Importance.NONE, environment=Importance.NONE),
        required_filters=[
            FilterClause(type="near", place="강남역", group="역세권"),
            FilterClause(type="near", place="홍대입구역", group="역세권"),
        ],
        top_n=3,
    ))
    dongs = {r["dong"] for r in result["recommendations"]}
    assert dongs == {"A동", "C동"}  # 둘 중 하나만 만족해도 통과 (OR)
    assert result["disqualified"][0]["dong"] == "B동"
    assert "중 근처 아님" in result["disqualified"][0]["missing"][0]


def test_recommend_near_without_group_is_and(monkeypatch, sample_raws):
    """group이 없으면(또는 서로 다르면) 여러 near 조건 전부 만족해야 한다(AND) —
    OR그룹 기능이 기존 AND 동작을 깨지 않는지 확인."""
    from app.agent import tools as tools_mod
    from app.schemas.tools import CategoryPreference, FilterClause, Importance, RecommendTool
    from tests.conftest import FakeRepo

    monkeypatch.setattr(tools_mod, "get_hybrid_facility_repository", lambda: _FakeMultiNearHybrid())
    result = tools_mod.ToolExecutor(FakeRepo(sample_raws)).recommend(RecommendTool(
        preference=CategoryPreference(
            safety=Importance.NONE, convenience=Importance.NONE,
            mobility=Importance.NONE, environment=Importance.NONE),
        required_filters=[
            FilterClause(type="near", place="강남역"),
            FilterClause(type="near", place="홍대입구역"),
        ],
        top_n=3,
    ))
    assert result["recommendations"] == []  # 둘 다 만족하는 동 없음 (AND)
