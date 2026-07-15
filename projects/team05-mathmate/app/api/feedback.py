"""단원별 진척도(피드백) API."""
from fastapi import APIRouter
from app.schemas.feedback import FeedbackResponse
from app.repositories import attempt_repo

router = APIRouter()


@router.get("/feedback", response_model=FeedbackResponse)
def get_feedback(user_id: int, grade: int | None = None, semester: int | None = None):
    items = attempt_repo.get_unit_mastery(user_id, grade, semester)   # avg_hints_used 내림차순 정렬됨
    weakest = items[0]["unit"] if items else None
    summary = attempt_repo.get_overall_summary(user_id, grade, semester)
    return FeedbackResponse(summary=summary, items=items, weakest_unit=weakest)
