from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health_check():
    """헬스체크 — Day1 기본 실행 확인용."""
    return {"status": "ok"}
