"""
도메인 스키마 — 행정동 424개 단위.

지표 처리 정책:
  - 반경 1km 내 개수형: conv/mart/hosp/bus/cctv/park (생활인구로 밀도화)
  - 최근접 거리형: subway (거리감쇠 0~1로 이미 변환됨)
  - 구 상속: crime_rate (소속 자치구 범죄율)
  - 행정동 고유: population (생활인구)

주의: 개수형 지표는 raw count를 담되, 스코어링에서 인구 대비 밀도로 정규화한다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# 카테고리별 가공 방식 각주 — 출구 LLM이 사용자가 중요시한 항목에 대해
# "숫자가 어떻게 만들어졌는지"를 함께 밝힐 때 근거로 인용한다 (실제 가공 근거 그대로).
CATEGORY_CAVEATS: dict[str, str] = {
    "safety": "범죄율은 행정동이 아닌 소속 자치구 값을 공통 적용합니다 (행정동 단위 범죄 데이터는 공개되지 않음).",
    "convenience": "편의점·마트·병원 수는 반경 1km 내 개수를 생활인구 대비 밀도로 정규화해 비교한 것입니다.",
    "mobility": "버스는 반경 1km 내 개수의 인구 대비 밀도, 지하철은 최근접 역까지 거리 기반 접근성(개수 아님)입니다.",
    "environment": "공원 수는 반경 1km 내 소공원까지 포함한 개수를 생활인구 대비 밀도로 비교한 것입니다.",
}


class DongRawMetrics(BaseModel):
    """행정동 1개의 원시 지표 (정규화 전)."""

    code: str = Field(..., description="행정동 코드 8자리")
    dong: str = Field(..., description="행정동명")
    gu: str = Field(..., description="자치구명")
    population: int = Field(..., gt=0, description="생활인구 (밀도 분모)")

    crime_rate: float = Field(..., ge=0, description="자치구 범죄율(1만명당, 구 상속)")
    cctv_cnt: int = Field(..., ge=0, description="반경 1km 내 CCTV 대수")

    conv_cnt: int = Field(..., ge=0, description="반경 1km 내 편의점 수")
    mart_cnt: int = Field(..., ge=0, description="반경 1km 내 마트 수")
    hosp_cnt: int = Field(..., ge=0, description="반경 1km 내 병원(종합병원급) 수")

    bus_cnt: int = Field(..., ge=0, description="반경 1km 내 버스정류소 수")
    subway_access: float = Field(..., ge=0, le=1, description="지하철 접근성(거리감쇠 0~1)")

    park_cnt: int = Field(..., ge=0, description="반경 1km 내 공원 수")


class DongScores(BaseModel):
    """행정동 1개의 카테고리별 정규화 점수 (0~1)."""

    code: str
    dong: str
    gu: str
    safety: float = Field(..., ge=0, le=1)
    convenience: float = Field(..., ge=0, le=1)
    mobility: float = Field(..., ge=0, le=1)
    environment: float = Field(..., ge=0, le=1)
    raw: DongRawMetrics


class Recommendation(BaseModel):
    """최종 추천 1건 (행정동 단위)."""

    rank: int = Field(..., ge=1)
    dong: str
    gu: str
    total_score: float = Field(..., ge=0, le=1)
    contributions: dict[str, float]
    scores: DongScores
