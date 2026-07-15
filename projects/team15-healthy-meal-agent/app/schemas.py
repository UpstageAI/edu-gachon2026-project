from typing import Literal, Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# 0. 요청 의도 (사용자 입력을 가장 먼저 분류)
# ─────────────────────────────────────────────
# 판단은 LLM, 사실은 코드 — 어떤 요청인지 "판단"만 LLM이 하고,
# 각 분기의 처리(추천/영양수치/거절)는 코드가 담당한다.
IntentType = Literal[
    "meal_recommend",  # 식단 추천 ("400kcal 가볍게 한 끼")
    "nutrition_query",  # 영양 조회 ("김치찌개 나트륨 얼마야?")
    "risky",  # 위험/부적절 요청 ("살 빼게 굶는 식단 짜줘")
    "out_of_scope",  # 범위 밖 ("오늘 날씨 어때?")
    "need_more_info",  # 조건 부족 ("뭐 먹지?") → 되묻기
]


# ─────────────────────────────────────────────
# 1. 사용자 프로필 (최초 1회 입력, 안전 확인용)
# ─────────────────────────────────────────────
class UserProfile(BaseModel):
    gender: Optional[Literal["male", "female"]] = None  # 성별 (건너뛸 수 있음)
    age_group: Optional[str] = None  # 연령대 예: "19-29"
    allergies: list[str] = Field(default_factory=list)  # 알레르기·못 먹는 음식 예: ["계란", "우유"]


# ─────────────────────────────────────────────
# 2. 사용자 추천 조건 (자연어에서 추출한 결과)
# ─────────────────────────────────────────────
class UserConditions(BaseModel):
    target_kcal: Optional[float] = None  # 목표 칼로리 예: 400
    kcal_mode: Optional[Literal["upper", "target"]] = None  # "upper"=이하 / "target"=정도
    preferences: list[str] = Field(default_factory=list)  # 선호 조건 예: ["야채 많은", "담백한"]
    wanted_foods: list[str] = Field(default_factory=list)  # 원하는 음식 예: ["비빔밥"]
    exclude_foods: list[str] = Field(
        default_factory=list
    )  # 제외 음식 예: ["계란"] (알레르기와 별개로 "빼줘"라고 한 것)
    nutrition_goals: list[str] = Field(
        default_factory=list
    )  # 영양/건강 목표 예: ["저염", "고단백"]
    meal_style: Optional[str] = None  # 식사 형태 예: "한그릇", "백반"
    previous_meal: Optional[str] = None  # 이전 식사 예: "떡볶이"


# ─────────────────────────────────────────────
# 3. 음식 하나 (foods_clean.csv의 한 줄)
# ─────────────────────────────────────────────
class FoodItem(BaseModel):
    food_id: int  # 음식 ID (삼삼한밥상 RCP_SEQ / 흰밥 90001~, 모두 정수)
    food_name: str  # 음식명
    meal_role: Literal["밥", "국물", "반찬", "한그릇", "간식", "기타"]  # 식사 내 역할
    serving_size: Optional[float] = None  # 1인분 기준량(g) — 삼삼한밥상은 76% 결측
    kcal: float  # 1인분 칼로리
    carbohydrate: float  # 탄수화물(g)
    protein: float  # 단백질(g)
    fat: float  # 지방(g)
    sugar: Optional[float] = None  # 당류(g) — 삼삼한밥상엔 당류 데이터 없음
    sodium: float  # 나트륨(mg)
    # 삼삼한 밥상 전용 (레시피 데이터). 구 데이터·흰밥은 빈 기본값.
    recipe_steps: list[str] = Field(default_factory=list)  # 조리 단계
    recipe_images: list[str] = Field(default_factory=list)  # 단계별 사진 URL
    ingredients: str = ""  # 재료 원문
    na_tip: str = ""  # 나트륨 저감팁


# ─────────────────────────────────────────────
# 4. 추천 식단 (음식 여러 개의 묶음)
# ─────────────────────────────────────────────
class MealPlan(BaseModel):
    meal_type: Literal["한그릇", "백반"]  # 식사 형태
    items: list[FoodItem]  # 포함된 음식들
    reason: str = ""  # 추천 이유


# ─────────────────────────────────────────────
# 5. 총 영양성분 (식단 전체 합산 결과)
# ─────────────────────────────────────────────
class NutritionTotal(BaseModel):
    total_kcal: float = 0
    total_carbohydrate: float = 0
    total_protein: float = 0
    total_fat: float = 0
    total_sugar: float = 0
    total_sodium: float = 0


# ─────────────────────────────────────────────
# 6. 검증 결과
# ─────────────────────────────────────────────
class ValidationResult(BaseModel):
    status: Literal["PASS", "PASS_WITH_WARNING", "FAIL"]  # 검증 등급
    warnings: list[str] = Field(default_factory=list)  # 주의 문구 (통과했지만 안내)
    failures: list[str] = Field(default_factory=list)  # 실패 이유 (재생성 트리거)
    # cause = 실패 원인. 재시도 때 어디로 돌아갈지 결정하는 핵심 필드
    cause: Optional[Literal["compose", "retrieve"]] = None  # compose=조합문제 / retrieve=후보문제


# ─────────────────────────────────────────────
# 7. Agent 상태 (전 과정을 들고 다니는 가방)
# ─────────────────────────────────────────────
class AgentState(BaseModel):
    user_message: str  # 사용자 원문
    profile: UserProfile = Field(default_factory=UserProfile)  # 프로필
    intent: Optional[IntentType] = None  # 요청 의도 (분류 결과)
    conditions: Optional[UserConditions] = None  # 추출된 조건
    candidates_by_role: dict[str, list[FoodItem]] = Field(default_factory=dict)  # 역할별 후보 dict
    candidates: list[FoodItem] = Field(default_factory=list)  # 검색된 후보들
    meal_plan: Optional[MealPlan] = None  # 구성된 식단
    nutrition_total: Optional[NutritionTotal] = None  # 합산 결과
    validation_result: Optional[ValidationResult] = None  # 검증 결과
    retry_count: int = 0  # 재시도 횟수
    final_response: str = ""  # 최종 응답
