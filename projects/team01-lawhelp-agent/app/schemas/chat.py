from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    thread_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    category: str
    guardrail_blocked: bool = False
    is_fallback: bool = False
    retrieved_count: int = 0
    response_type: str = "normal"
    warning: Optional[str] = None
    suggested_questions: list[dict[str, str]] = Field(default_factory=list)
    sources: list[dict[str, str]] = Field(default_factory=list)
    is_grounded: bool = False
    # 평가(Hit@3)용 원시 검색 top-3 (라우팅 채택 여부와 무관). 검색 미실행 경로는 빈 리스트.
    top_documents: list[dict] = Field(default_factory=list)
