"""즐겨찾기 라우트 — 로그인 사용자별 관심 종목 조회/추가/삭제."""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.repositories import watchlist as wl_repo
from app.schemas.auth import WatchlistAddRequest

router = APIRouter()


@router.get("/")
async def list_watchlist(user: dict = Depends(get_current_user)) -> dict:
    items = await wl_repo.list_user_watchlist(user["user_id"])
    return {"items": items}


@router.post("/")
async def add_watchlist(
    req: WatchlistAddRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    return await wl_repo.add_user_watchlist(
        user_id=user["user_id"],
        ticker=req.ticker,
        name=req.name or req.ticker,
    )


@router.delete("/{ticker}")
async def remove_watchlist(
    ticker: str,
    user: dict = Depends(get_current_user),
) -> dict:
    await wl_repo.remove_user_watchlist(user_id=user["user_id"], ticker=ticker)
    return {"removed": True, "ticker": ticker}
