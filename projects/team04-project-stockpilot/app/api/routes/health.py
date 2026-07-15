"""헬스체크 라우트."""
from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def health_check() -> dict:
    """서버 생존 확인. 배포 환경의 헬스체크가 호출한다."""
    return {
        "status": "healthy",
        "service": "stockpilot",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
