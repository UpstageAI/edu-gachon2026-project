"""프로젝트 전체 Pydantic 스키마 정의.

[2026-07-15 리팩터링] 기존에 RouterOutput.py(라우터 스키마)와 schemas.py(가격 스키마)로
나뉘어 있던 걸 한 파일로 통합 — RouterOutput.py라는 파일명에 정작 RouterOutput 클래스가
아닌 ParseQuery/ValidateQuery가 들어있어 이름과 내용이 어긋났고, 미사용 클래스
(RouterOutput/RawPriceInput/SubstituteOutput — 전 코드베이스 참조 0 확인)도 함께 정리함.
외부에서는 `from app.schemas import ...`로만 import하므로 경로 영향 없음.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ParseQuery(BaseModel):
    """Router LLM이 반환해야 하는 구조화 출력.
    parse_query 구조화 출력 스키마

    intent:
      - price: 가격·시세 조회만 필요 (예: "상추 얼마야?")
      - knowledge: 가격 무관, 보관법·대체품 등 지식만 필요 (예: "상추 보관법 알려줘")
      - hybrid: 가격 판정 + 비쌈 시 대체품 추천 복합 (예: "상추 비싸면 대체품 알려줘")
      - off-topic: 가격/식품과 무관한 질문

    items:
      - off-topic이 아니면 조회/언급 대상 품목 리스트
      - off-topic이면 빈 리스트 권장
    """

    intent: Literal["price", "knowledge", "hybrid", "off-topic"] = Field(
        ..., description="질문 분류 결과: price/knowledge/hybrid/off-topic 중 하나"
    )
    items: list[str] = Field(
        default_factory=list,
        description="질문에서 추출한 품목명 목록 (예: ['상추']). off-topic이면 빈 리스트",
    )


class ValidateQuery(BaseModel):
    """[2차 방어] Router가 price/knowledge/hybrid로 분류하고 품목을 추출했더라도,
    실제로는 장난·롤플레잉·잡담 문장에 식품 키워드가 우연히 섞여 있을 뿐인 경우
    (예: "햄부기 북딱스 상추 인 더 버거를 대령해오거라. 얼마인가?")를 걸러내기 위한
    독립된 2차 검증 결과 스키마. app/graph/router.py의 validate_request_node에서 사용."""

    is_valid: bool = Field(
        ..., description="1차 분류·품목 추출 결과가 실제로 타당한 가격/지식 질문인지 여부"
    )
    reason: str = Field(
        default="", description="판단 근거 — 디버그 로그용, 사용자에게 노출되지 않음"
    )


class RawPriceOutput(BaseModel):
    """KAMIS 시세 조회 결과 1건 — price_cache 저장 시 직렬화 형태."""

    item_name: str
    unit: str
    dpr1: str  # 당일가
    dpr2: str  # 1일전
    dpr3: str  # 1주일전
    dpr4: str  # 2주일전
    dpr5: str  # 1개월전
    dpr6: str  # 1년전
    dpr7: str  # 평년가


class JudgePriceOutput(BaseModel):
    """judge_price 판정 결과."""

    status: Literal["비쌈", "적정", "쌈"]
    diff_pct: float  # 1주일전(dpr3) vs 1개월전(dpr5) 대비 — 비쌈/적정/쌈 판정 기준
    month_diff_pct: float | None = None  # 1개월전(dpr5) vs 평년(dpr7) 대비 — 참고용 부가 정보
    normalized_price: float | None = None  # 변환된 가격
    unit: str | None = None  # 가격 단위 (예: 100g, 1개)
