"""Supabase users 저장소."""
from __future__ import annotations

from typing import Any

from app.repositories import get_supabase_client


async def create_user(username: str, password_hash: str) -> dict[str, Any]:
    """새 사용자를 저장한다. username 중복은 DB unique 제약으로 막힌다."""
    client = await get_supabase_client()
    result = await (
        client.table("users")
        .insert({"username": username, "password_hash": password_hash})
        .execute()
    )
    return result.data[0]


async def get_user_by_username(username: str) -> dict[str, Any] | None:
    """username으로 사용자를 조회한다. 없으면 None."""
    client = await get_supabase_client()
    result = await (
        client.table("users")
        .select("*")
        .eq("username", username)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None
