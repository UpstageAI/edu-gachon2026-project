"""Pydantic 스키마 — Tool 입출력 및 API 요청 구조화."""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    student_id: str
    problem_id: str
    message: str


class Hint(BaseModel):
    """generate_hint 도구의 구조화 출력."""
    hint_text: str = Field(..., description="학생에게 보여줄 힌트 (정답 미포함)")
    level: int = Field(..., ge=1, le=3, description="힌트 구체화 단계")
    contains_answer: bool = Field(..., description="정답 포함 여부 자체 플래그")


class Diagnosis(BaseModel):
    """diagnose_step 도구의 출력."""
    stuck_point: str = Field("", description="학생이 막힌/틀린 지점")
    is_correct: bool = Field(..., description="학생 답(중간 단계 포함)이 맞았는지")
    solved: bool = Field(False, description="최종 정답에 도달했는지")
