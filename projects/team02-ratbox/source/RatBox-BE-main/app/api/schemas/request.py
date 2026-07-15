from uuid import UUID

from pydantic import BaseModel, Field


class RecommendRequest(BaseModel):
    ingredient_ids: list[str] = Field(
        ..., description="사용자가 목록에서 선택한 재료 id 목록 (ingredients_master.id)"
    )
    allergen_ids: list[str] = Field(
        default_factory=list, description="사용자의 등록된 알레르기 id 목록 (allergen_master.id)"
    )
    recipe_id: str | None = Field(
        None, description="후보 3개 중 사용자가 선택한 레시피 id. 없으면 후보 추천 단계로 처리"
    )


class SignupRequest(BaseModel):
    username: str = Field(..., min_length=4, max_length=20, description="로그인 아이디")
    password: str = Field(..., min_length=8, description="비밀번호")
    name: str = Field(..., min_length=1, description="사용자 이름")


class LoginRequest(BaseModel):
    username: str = Field(..., description="로그인 아이디")
    password: str = Field(..., description="비밀번호")


class RegisterAllergensRequest(BaseModel):
    allergen_ids: list[UUID] = Field(
        default_factory=list,
        description="사용자가 선택한 알레르기 id 목록 (0개, 1개, 여러 개 모두 가능)",
    )


class UpdateMyInfoRequest(BaseModel):
    username: str | None = Field(None, min_length=4, max_length=20, description="로그인 아이디")
    name: str | None = Field(None, min_length=1, description="사용자 이름")


class ConfirmIngredientSelectionRequest(BaseModel):
    category_id: UUID = Field(..., description="사용자가 화면에서 선택한 재료 카테고리 id")


class VoiceQueryRequest(BaseModel):
    recipe_id: str = Field(..., description="현재 조리 중인 레시피 id")
    allergen_ids: list[str] = Field(
        default_factory=list, description="사용자의 등록된 알레르기 id 목록"
    )
    question: str = Field(..., min_length=1, description="STT로 변환된 사용자 질문 텍스트")
    current_step_text: str | None = Field(
        None,
        description=(
            "FE가 지금 화면에 보여주고 있는 조리 단계 원문. 답변의 참고용 힌트로만 쓰이며, "
            "이 내용을 벗어나는 질문도 일반 조리 지식으로 답변 가능하다."
        ),
    )
