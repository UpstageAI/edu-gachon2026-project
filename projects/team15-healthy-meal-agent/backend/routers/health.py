"""
backend/routers/health.py
헬스체크 엔드포인트.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/api/v1/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
