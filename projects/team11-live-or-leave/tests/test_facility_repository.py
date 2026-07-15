"""data/facility_repository.py 단위 테스트 (합성 CSV — 실제 74MB 파일과 독립)."""
from __future__ import annotations

from app.data.facility_repository import FacilityRepository

_HEADER = ("상가업소번호,상호명,상권업종대분류명,상권업종중분류명,상권업종소분류명,"
           "시군구명,행정동명,법정동명,경도,위도")


def _row(gu: str, dong: str, category: str) -> str:
    return f"1,테스트가게,음식,기타,{category},{gu},{dong},{dong},127.0,37.5"


def test_count_aggregates_by_gu_dong_category(tmp_path):
    csv_path = tmp_path / "facilities.csv"
    csv_path.write_text("\n".join([
        _HEADER,
        _row("강남구", "역삼동", "버거"),
        _row("강남구", "역삼동", "버거"),
        _row("강남구", "역삼동", "헬스장"),
        _row("서초구", "서초동", "버거"),
    ]), encoding="utf-8-sig")

    repo = FacilityRepository(csv_path)
    assert repo.count("강남구", "역삼동", "버거") == 2
    assert repo.count("강남구", "역삼동", "헬스장") == 1
    assert repo.count("서초구", "서초동", "버거") == 1


def test_count_returns_zero_for_unknown_combo(tmp_path):
    csv_path = tmp_path / "facilities.csv"
    csv_path.write_text("\n".join([_HEADER, _row("강남구", "역삼동", "버거")]),
                         encoding="utf-8-sig")
    repo = FacilityRepository(csv_path)
    assert repo.count("강남구", "없는동", "버거") == 0
    assert repo.count("강남구", "역삼동", "없는업종") == 0


def test_categories_returns_all_distinct_labels(tmp_path):
    csv_path = tmp_path / "facilities.csv"
    csv_path.write_text("\n".join([
        _HEADER,
        _row("강남구", "역삼동", "버거"),
        _row("강남구", "역삼동", "헬스장"),
    ]), encoding="utf-8-sig")
    repo = FacilityRepository(csv_path)
    assert repo.categories() == {"버거", "헬스장"}


def test_same_dong_name_in_different_gu_is_not_confused(tmp_path):
    """동명이인(신사동 등) 방지 — (구,동) 조합으로 구분해야 한다."""
    csv_path = tmp_path / "facilities.csv"
    csv_path.write_text("\n".join([
        _HEADER,
        _row("강남구", "신사동", "버거"),
        _row("은평구", "신사동", "버거"),
        _row("은평구", "신사동", "버거"),
    ]), encoding="utf-8-sig")
    repo = FacilityRepository(csv_path)
    assert repo.count("강남구", "신사동", "버거") == 1
    assert repo.count("은평구", "신사동", "버거") == 2


def test_get_facility_repository_caches_instance(monkeypatch):
    import app.data.facility_repository as facility_repository_module

    monkeypatch.setattr(facility_repository_module, "_cache", None)
    calls = []

    class FakeRepo:
        def __init__(self):
            calls.append(1)

    monkeypatch.setattr(facility_repository_module, "FacilityRepository", FakeRepo)

    a = facility_repository_module.get_facility_repository()
    b = facility_repository_module.get_facility_repository()
    assert a is b
    assert len(calls) == 1
