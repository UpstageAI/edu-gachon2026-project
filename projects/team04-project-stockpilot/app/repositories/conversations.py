"""Supabase 대화 저장소 — 로그인 사용자별 대화(제목·메시지·인사이트)를 저장한다."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.repositories import get_supabase_client


async def list_conversations(user_id: int) -> list[dict[str, Any]]:
    """내 대화 목록을 최신순으로 반환한다."""
    client = await get_supabase_client()
    result = await (
        client.table("conversations")
        .select("data")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .execute()
    )
    return [row["data"] for row in (result.data or []) if row.get("data")]


async def upsert_conversation(user_id: int, conv: dict[str, Any]) -> None:
    """대화 1건 저장(있으면 갱신)."""
    conv_id = conv.get("id")
    if not conv_id:
        return
    client = await get_supabase_client()
    await (
        client.table("conversations")
        .upsert(
            {
                "id": conv_id,
                "user_id": user_id,
                "data": conv,
                "updated_at": datetime.now(UTC).isoformat(),
            },
            on_conflict="id",
        )
        .execute()
    )


async def upsert_many(user_id: int, convs: list[dict[str, Any]]) -> None:
    """여러 대화를 저장한다(로그인 시 게스트 대화 이전용)."""
    for conv in convs:
        await upsert_conversation(user_id, conv)


async def delete_conversation(user_id: int, conv_id: str) -> None:
    """내 대화 1건 삭제."""
    client = await get_supabase_client()
    await (
        client.table("conversations")
        .delete()
        .eq("id", conv_id)
        .eq("user_id", user_id)
        .execute()
    )
