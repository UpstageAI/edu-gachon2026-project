"""학습 진척도 조회 (힌트 사용량 KPI)."""
from fastapi import APIRouter
from app.repositories import progress_repo

router = APIRouter()


@router.get("/progress/{student_id}")
def get_progress(student_id: str):
    """문제별 진척도 목록 + 요약."""
    return {"summary": progress_repo.summary(student_id),
            "items": progress_repo.get_progress(student_id)}
