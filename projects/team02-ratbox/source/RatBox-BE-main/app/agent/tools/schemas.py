from typing import Literal

from pydantic import BaseModel, Field

from app.domain.models import RecipeCandidate, SubstituteCandidate


class GenerateSQLInput(BaseModel):
    ingredients: list[str] = Field(..., description="사용자가 목록에서 선택한 재료명 목록")
    strategy: Literal["exact", "relaxed"] = Field(
        "exact",
        description=(
            "exact: 보유 재료가 하나라도 겹치는 레시피를 정확한 이름 매칭으로 찾는다. "
            "relaxed: exact로 0건이 나왔을 때, 재료 카테고리 기준으로 조건을 완화해 다시 찾는다. "
            "재료가 흔하고 대체 가능성이 높을 때만 relaxed를 선택하라."
        ),
    )


class GenerateSQLOutput(BaseModel):
    sql: str = Field(
        ..., description="recipes/recipe_ingredients/ingredients_master만 참조하는 단일 SELECT문"
    )


class ExecuteSQLInput(BaseModel):
    sql: str = Field(..., description="generate_sql이 만든 SELECT문")


class ExecuteSQLOutput(BaseModel):
    recipes: list[RecipeCandidate]
    error: str | None = Field(None, description="검증/실행 실패 시 에러 메시지, 성공 시 None")


class ClassifyMissingInput(BaseModel):
    recipe_id: str
    available_ingredients: list[str]


class ClassifyMissingOutput(BaseModel):
    required: list[str] = Field(..., description="빠지면 조리가 불가능한 필수 재료명")
    optional: list[str] = Field(..., description="없어도 조리 가능한 생략 가능 재료명")
    reason: str = Field(..., description="필수/생략가능 판단 근거")


class FindSubstitutesInput(BaseModel):
    ingredient_name: str = Field(..., description="대체재를 찾을 부족 재료명")
    recipe_name: str = Field(..., description="이 재료가 쓰이는 레시피명")
    recipe_context: str | None = Field(None, description="레시피의 조리 맥락(카테고리, 조리법 등)")
    exclude_ingredients: list[str] = Field(
        default_factory=list,
        description=(
            "이미 이 레시피에 쓰이는 다른 재료명 목록. "
            "대체재로 추천하면 안 됨(이미 쓰이고 있어 무의미)."
        ),
    )
    owned_ingredients: list[str] = Field(
        default_factory=list,
        description="사용자가 이미 가진 재료명 목록. 대체재를 고를 때 이 중에서 우선 추천해야 함.",
    )


class FindSubstitutesOutput(BaseModel):
    substitutes: list[SubstituteCandidate]
    reason: str = Field(..., description="대체재 제안 근거")


class GenerateCookingStepsOutput(BaseModel):
    steps: list[str] = Field(
        ...,
        description="처음부터 완성까지의 조리 순서. 각 항목은 한 동작만 담은 짧은 문장, 3~8단계",
    )
