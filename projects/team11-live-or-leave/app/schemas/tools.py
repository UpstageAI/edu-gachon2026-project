"""
에이전트 도구 스키마 — LLM이 채우는 구조화된 입출력 정의.

핵심 설계 (앞선 논의 반영):
  - LLM은 '숫자'를 직접 만들지 않는다. 4단계 라벨(중요도)만 고르게 하고,
    라벨→가중치 매핑은 결정론적 코드가 수행한다. (일관성 확보)
  - 가중치 합=1 정규화, 파싱 실패 시 폴백은 서비스 계층 책임.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Importance(str, Enum):
    """카테고리 중요도 라벨. LLM은 이 중 하나만 선택한다."""

    VERY_HIGH = "very_high"   # 매우 중요
    HIGH = "high"             # 중요
    MEDIUM = "medium"         # 보통
    NONE = "none"             # 관계없음


# 라벨 → 고정 점수 매핑 (코드가 소유, LLM이 건드리지 않음)
IMPORTANCE_SCORE: dict[Importance, float] = {
    Importance.VERY_HIGH: 1.0,
    Importance.HIGH: 0.6,
    Importance.MEDIUM: 0.3,
    Importance.NONE: 0.0,
}


class FilterClause(BaseModel):
    """필수 요구사항 1건 — type에 따라 아래 필드 중 해당하는 것만 채워진다.

    거리(near)·행정구역(gu) 2종류를 하나의 목록(RecommendTool.required_filters)
    으로 표현한다. LLM이 자연어에서 추론하지 않는다 — 사용자가 UI에서 직접
    고른 구조화 입력(구 멀티셀렉트, 기준 장소 텍스트)을 그대로 옮겨 담는다.
    그래서 ParsedIntent에는 이 필드가 없다: LLM 출력과 required_filters는
    이제 완전히 분리된 경로다(loop.py가 둘을 합쳐 RecommendTool을 만든다).

    업종 존재(category)·대형병원(require_large_hospital) 하드필터는 제거됐다
    (app/agent/tools.py 모듈 docstring에 사유 기록)."""

    type: Literal["near", "gu"]

    # type="near" — 거리 필터 (기준 장소: 랜드마크·회사·주소 등 임의 장소)
    place: str | None = Field(default=None, description="'서울대', '강남역' 등 기준 장소명")
    lon: float | None = Field(
        default=None,
        description="기준 장소 좌표(경도)를 이미 알 때 직접 지정. UI에서 Kakao 검색 후보 "
        "여러 개 중 사용자가 하나를 골랐을 때 그 좌표를 그대로 쓴다 — 있으면 place로 다시 "
        "검색하지 않는다(재검색 시 top-1이 사용자가 고른 것과 다를 수 있어서).",
    )
    lat: float | None = Field(default=None, description="기준 장소 좌표(위도). lon과 함께 채운다")
    radius_km: float | None = Field(
        default=None, description="반경(km). 생략하면 기본값(3km) 사용"
    )
    group: str | None = Field(
        default=None,
        description="같은 group명을 가진 near 조건끼리는 OR(하나만 만족해도 통과), "
        "group이 없거나 서로 다르면 AND. '강남역이나 홍대입구역 중 아무데나' 같은 "
        "경우에만 채우고, 보통은 비워둔다.",
    )

    # type="gu" — 행정구역 포함/제외
    gu: list[str] | None = Field(
        default=None, description="자치구명 목록(예: ['강남구']) 또는 '강남3구' 같은 통칭"
    )
    exclude: bool = Field(
        default=False, description="True면 이 구들을 제외(그 외 지역만), False면 이 구들 안에서만"
    )


class CategoryPreference(BaseModel):
    """입구 LLM의 출력 스키마 — 카테고리별 중요도 라벨."""

    safety: Importance = Field(..., description="안전(범죄 적고 CCTV 많음) 중요도")
    convenience: Importance = Field(..., description="편의(편의점·마트·병원) 중요도")
    mobility: Importance = Field(..., description="이동(지하철·버스 접근성) 중요도")
    environment: Importance = Field(..., description="환경(공원·녹지) 중요도")


class ParsedIntent(BaseModel):
    """입구 LLM 전체 출력 — 선호 + 되묻기 여부.

    required_filters(구·근처)는 여기 없다 — 사용자가 UI에서 직접 입력하는
    구조화 값이라 LLM이 볼 필요도, 지어낼 여지도 없다. loop.py가 이 출력과
    UI가 준 required_filters를 나중에 합쳐 RecommendTool을 만든다."""

    preference: CategoryPreference
    extra_categories: list[str] = Field(
        default_factory=list,
        description="'버거집', '헬스장' 같이 4개 카테고리 밖에서 '선택'으로 언급된 업종 — "
        "점수에 반영(가중치 참여). 실제 존재하는 상권업종소분류명 문자열로만 채운다 (자유 생성 금지)",
    )
    needs_clarification: bool = Field(
        default=False, description="성향이 모호해 되물어야 하면 True"
    )
    clarify_question: str | None = Field(
        default=None, description="되물을 질문 (needs_clarification=True일 때)"
    )


# ---- 도구(tool) 입출력 스키마 : ReAct 루프에서 LLM이 호출 ----

class RecommendTool(BaseModel):
    """도구: 선호를 받아 상위 N개 자치구 추천.

    required_filters는 ParsedIntent가 아니라 UI의 구조화 입력(구 멀티셀렉트,
    기준 장소)에서 직접 채워진다 — LLM 출력이 아니다."""

    preference: CategoryPreference
    extra_categories: list[str] = Field(default_factory=list)
    required_filters: list[FilterClause] = Field(default_factory=list)
    top_n: int = Field(default=3, ge=1, le=500)


class CompareTool(BaseModel):
    """도구: 두 자치구의 지표 비교."""

    gu_a: str
    gu_b: str


class ClarifyTool(BaseModel):
    """도구: 사용자에게 되묻기."""

    question: str
