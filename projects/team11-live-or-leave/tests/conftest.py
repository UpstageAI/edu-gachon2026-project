"""공용 테스트 픽스처.

score_dongs()의 계산을 손으로 검증할 수 있도록, population을 전부 10000으로
맞춰 밀도(=count) 계산을 단순화한 합성 데이터를 사용한다.
"""
from __future__ import annotations

import pytest

from app.schemas.domain import DongRawMetrics


@pytest.fixture(autouse=True)
def _no_live_api_calls(monkeypatch):
    """실 API 키가 로컬 쉘/.env에 있어도 테스트가 실제 호출·과금하지 않게 강제한다.
    (RecommendationAgent가 UPSTAGE 키 유무로 SolarLLM/MockLLM을 자동 선택하고,
    KakaoFacilityRepository는 KAKAO 키 유무로 available()을 판단한다. 필요한
    테스트만 monkeypatch.setenv로 개별 설정한다.)"""
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)


def _raw(code, dong, gu, **kw):
    base = dict(
        population=10000, crime_rate=0, cctv_cnt=0,
        conv_cnt=0, mart_cnt=0, hosp_cnt=0,
        bus_cnt=0, subway_access=0.0, park_cnt=0,
    )
    base.update(kw)
    return DongRawMetrics(code=code, dong=dong, gu=gu, **base)


@pytest.fixture
def sample_raws() -> list[DongRawMetrics]:
    """3개 행정동, 지표별 밀도 동률 없이 설계 (수동 계산한 기대값과 1:1 대응).

    기대 결과 (score_dongs 기준):
      A: safety=1.0, convenience=0.5, mobility=1.0, environment=1.0, hosp_cnt=2
      B: safety=0.0, convenience=0.3, mobility=0.0, environment=0.0, hosp_cnt=0
      C: safety=0.5, convenience=0.7, mobility=0.5, environment=0.5, hosp_cnt=1
    """
    return [
        _raw("A1", "A동", "강남구", crime_rate=10, cctv_cnt=30,
             conv_cnt=40, mart_cnt=5, hosp_cnt=2,
             bus_cnt=60, subway_access=0.9, park_cnt=10),
        _raw("B1", "B동", "강남구", crime_rate=30, cctv_cnt=10,
             conv_cnt=20, mart_cnt=15, hosp_cnt=0,
             bus_cnt=20, subway_access=0.3, park_cnt=3),
        _raw("C1", "C동", "서초구", crime_rate=20, cctv_cnt=20,
             conv_cnt=60, mart_cnt=10, hosp_cnt=1,
             bus_cnt=40, subway_access=0.6, park_cnt=6),
    ]


@pytest.fixture
def no_hospital_raws() -> list[DongRawMetrics]:
    """대형병원 필터 폴백(전부 hosp_cnt=0) 검증용 2개 행정동."""
    return [
        _raw("D1", "D동", "마포구", hosp_cnt=0, population=10000),
        _raw("E1", "E동", "마포구", hosp_cnt=0, population=10000),
    ]


class FakeRepo:
    """CsvDongRepository와 동일한 인터페이스의 인메모리 저장소 (테스트용)."""

    def __init__(self, raws: list[DongRawMetrics]):
        self._raws = list(raws)

    def all_metrics(self) -> list[DongRawMetrics]:
        return list(self._raws)

    def get(self, dong: str):
        return next((m for m in self._raws if m.dong == dong), None)
