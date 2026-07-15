"""
CSV 기반 저장소 (행정동 단위) — build_dong_metrics.py 산출물을 읽는다.
mock/실데이터/SQL 교체 시 이 계층만 바뀌고 상위는 불변.
"""
from __future__ import annotations

import csv
from pathlib import Path

from app.schemas.domain import DongRawMetrics

DEFAULT_CSV = Path(__file__).resolve().parents[2] / "dong_metrics.csv"


class CsvDongRepository:
    def __init__(self, csv_path: str | Path = DEFAULT_CSV):
        self._metrics: list[DongRawMetrics] = []
        with open(csv_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                pop = int(row["population"])
                if pop <= 0:
                    continue  # 생활인구 0인 동 제외 (밀도 계산 불가)
                self._metrics.append(DongRawMetrics(
                    code=row["code"], dong=row["dong"], gu=row["gu"],
                    population=pop,
                    crime_rate=float(row["crime_rate"]),
                    cctv_cnt=int(row["cctv_cnt"]),
                    conv_cnt=int(row["conv_cnt"]),
                    mart_cnt=int(row["mart_cnt"]),
                    hosp_cnt=int(row["hosp_cnt"]),
                    bus_cnt=int(row["bus_cnt"]),
                    subway_access=float(row["subway_access"]),
                    park_cnt=int(row["park_cnt"]),
                ))

    def all_metrics(self) -> list[DongRawMetrics]:
        return list(self._metrics)

    def get(self, dong: str) -> DongRawMetrics | None:
        return next((m for m in self._metrics if m.dong == dong), None)
