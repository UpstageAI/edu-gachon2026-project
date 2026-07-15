"""대화 라우트 — 로그인 사용자별 대화 저장/조회/삭제. 실패해도 앱은 계속 동작한다."""
from typing import Any

from fastapi import APIRouter, Depends
from loguru import logger

from app.api.deps import get_current_user
from app.repositories import conversations as conv_repo

router = APIRouter()


@router.get("/")
async def list_my_conversations(user: dict = Depends(get_current_user)) -> list[dict[str, Any]]:
    """내 계정의 대화 목록(최신순)."""
    try:
        return await conv_repo.list_conversations(user["user_id"])
    except Exception as exc:
        logger.warning(f"대화 목록 조회 실패: {type(exc).__name__}: {exc}")
        return []


@router.put("/")
async def save_conversation(conv: dict[str, Any], user: dict = Depends(get_current_user)) -> dict:
    """대화 1건 저장(upsert)."""
    try:
        await conv_repo.upsert_conversation(user["user_id"], conv)
        return {"ok": True}
    except Exception as exc:
        logger.warning(f"대화 저장 실패: {type(exc).__name__}: {exc}")
        return {"ok": False}


@router.post("/bulk")
async def save_conversations_bulk(convs: list[dict[str, Any]], user: dict = Depends(get_current_user)) -> dict:
    """여러 대화 저장(로그인 시 게스트 대화 이전용)."""
    try:
        await conv_repo.upsert_many(user["user_id"], convs)
        return {"ok": True, "count": len(convs)}
    except Exception as exc:
        logger.warning(f"대화 일괄 저장 실패: {type(exc).__name__}: {exc}")
        return {"ok": False}


@router.delete("/{conv_id}")
async def delete_my_conversation(conv_id: str, user: dict = Depends(get_current_user)) -> dict:
    """내 대화 1건 삭제."""
    try:
        await conv_repo.delete_conversation(user["user_id"], conv_id)
        return {"ok": True}
    except Exception as exc:
        logger.warning(f"대화 삭제 실패: {type(exc).__name__}: {exc}")
        return {"ok": False}
