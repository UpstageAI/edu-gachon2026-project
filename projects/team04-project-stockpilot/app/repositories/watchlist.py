"""Supabase 관심 종목 저장소."""

from __future__ import annotations

from typing import Any

from app.repositories import get_supabase_client


async def add_watchlist(
    *,
    ticker: str,
    name: str,
    session_id: str,
) -> dict[str, Any]:
    if not session_id.strip():
        raise ValueError("session_id가 필요합니다.")

    client = await get_supabase_client()
    payload = {
        "session_id": session_id,
        "ticker": ticker,
        "name": name,
    }
    result = await (
        client.table("watchlists")
        .upsert(payload, on_conflict="session_id,ticker")
        .execute()
    )
    row = result.data[0] if result.data else payload
    return {**row, "saved": True}


async def list_user_watchlist(user_id: int) -> list[dict[str, Any]]:
    """로그인 사용자의 즐겨찾기 목록을 최신순으로 조회한다."""
    client = await get_supabase_client()
    result = await (
        client.table("watchlists")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


async def add_user_watchlist(
    *,
    user_id: int,
    ticker: str,
    name: str,
) -> dict[str, Any]:
    """로그인 사용자의 즐겨찾기에 종목을 중복 없이 추가한다."""
    client = await get_supabase_client()
    payload = {"user_id": user_id, "ticker": ticker, "name": name}
    result = await (
        client.table("watchlists")
        .upsert(payload, on_conflict="user_id,ticker")
        .execute()
    )
    row = result.data[0] if result.data else payload
    return {**row, "saved": True}


async def remove_user_watchlist(*, user_id: int, ticker: str) -> None:
    """로그인 사용자의 즐겨찾기에서 종목을 제거한다."""
    client = await get_supabase_client()
    await (
        client.table("watchlists")
        .delete()
        .eq("user_id", user_id)
        .eq("ticker", ticker)
        .execute()
    )
