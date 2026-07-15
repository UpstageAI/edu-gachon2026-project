"""data/csv_repository.py 단위 테스트.

합성 CSV(population<=0 필터링 등 동작 검증)와 실제 dong_metrics.csv(적재 자체
검증)를 모두 다룬다.
"""
from __future__ import annotations

from app.data.csv_repository import DEFAULT_CSV, CsvDongRepository

_HEADER = ("code,dong,gu,population,crime_rate,cctv_cnt,conv_cnt,mart_cnt,"
           "hosp_cnt,bus_cnt,subway_access,park_cnt")


def _row(**kw) -> str:
    d = dict(code="1", dong="d", gu="g", population="100", crime_rate="1.0",
              cctv_cnt="1", conv_cnt="1", mart_cnt="1", hosp_cnt="1",
              bus_cnt="1", subway_access="0.5", park_cnt="1")
    d.update(kw)
    return ",".join(str(d[k]) for k in
                     ("code", "dong", "gu", "population", "crime_rate", "cctv_cnt",
                      "conv_cnt", "mart_cnt", "hosp_cnt", "bus_cnt", "subway_access",
                      "park_cnt"))


def test_rows_with_zero_or_negative_population_are_excluded(tmp_path):
    csv_path = tmp_path / "synthetic.csv"
    csv_path.write_text(
        "\n".join([
            _HEADER,
            _row(code="1", dong="살아있는동", population="100"),
            _row(code="2", dong="인구없는동", population="0"),
        ]),
        encoding="utf-8-sig",
    )
    repo = CsvDongRepository(csv_path)
    dongs = {m.dong for m in repo.all_metrics()}
    assert dongs == {"살아있는동"}


def test_get_returns_matching_dong_by_name(tmp_path):
    csv_path = tmp_path / "synthetic.csv"
    csv_path.write_text(
        "\n".join([_HEADER, _row(code="1", dong="역삼동", population="100")]),
        encoding="utf-8-sig",
    )
    repo = CsvDongRepository(csv_path)
    assert repo.get("역삼동").code == "1"
    assert repo.get("존재하지않는동") is None


def test_all_metrics_returns_independent_copy(tmp_path):
    csv_path = tmp_path / "synthetic.csv"
    csv_path.write_text(
        "\n".join([_HEADER, _row(code="1", dong="역삼동", population="100")]),
        encoding="utf-8-sig",
    )
    repo = CsvDongRepository(csv_path)
    result = repo.all_metrics()
    result.clear()
    assert len(repo.all_metrics()) == 1


def test_default_csv_loads_without_error():
    assert DEFAULT_CSV.exists()
    repo = CsvDongRepository()
    metrics = repo.all_metrics()
    assert len(metrics) > 400  # HANDOFF.md 기준 행정동 424~425개
    assert all(m.population > 0 for m in metrics)
    assert len({m.code for m in metrics}) == len(metrics)  # 코드 중복 없음
