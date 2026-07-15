"""
backend/schemas.py
API 전용 요청/응답 스키마.
도메인 스키마(app/schemas.py)는 그대로 재사용하고,
여기서는 '정문'에서만 필요한 요청 래퍼와 응답 형태만 최소로 정의한다.
스키마 중복 정의 금지 원칙에 따라 FoodItem/NutritionTotal 등은 재사용한다.
"""

from typing import Optional

from pydantic import BaseModel, Field

from app.schemas import FoodItem, IntentType, NutritionTotal, UserProfile


# ─────────────────────────────────────────────
# 요청
# ─────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str = Field(..., description="사용자 자연어 요청", min_length=1)
    profile: Optional[UserProfile] = None  # 없으면 기본 프로필
    thread_id: Optional[str] = None  # 멀티턴 식별자(대화별). 없으면 단발 요청(무상태)


# ─────────────────────────────────────────────
# 응답
# 프론트가 카드로 그릴 수 있도록 run_agent(AgentState)를 평평하게 정리한다.
# ─────────────────────────────────────────────
class ChatResponse(BaseModel):
    intent: Optional[IntentType] = None  # 요청 분류 결과 (프론트 분기·투명성용)
    meal_type: Optional[str] = None  # "한그릇" / "백반" (추천 실패 시 None)
    items: list[FoodItem] = Field(default_factory=list)  # 추천 음식들
    nutrition: Optional[NutritionTotal] = None  # 총 영양성분
    reason: str = ""  # 추천 이유
    status: Optional[str] = None  # 검증 등급 PASS / PASS_WITH_WARNING / FAIL / None
    warnings: list[str] = Field(default_factory=list)  # 주의 문구
    final_response: str = ""  # 사람이 읽는 최종 텍스트
    retry_count: int = 0  # 재시도 횟수 (디버깅/투명성용)
