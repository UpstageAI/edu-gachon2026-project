"""Discord 봇 발송 — services 레이어.
   DELIVERY_DRY_RUN=true(기본) 이면 실제 전송 없이 상태만. 봇 토큰/채널 없으면 skipped."""
from __future__ import annotations

import os


def dry_run() -> bool:
    return os.getenv("DELIVERY_DRY_RUN", "true").lower() != "false"


def format_card_text(card: dict) -> str:
    return (f"[{card.get('category', '')}] {card.get('headline', '')}\n"
            f"{card.get('lead', '')}\n{card.get('body', '')}\n"
            f"{card.get('source', '')} · {card.get('disclaimer', '')}")


def send_via_bot(*, channel_id: str, text: str, image_path: str | None = None) -> dict:
    """Discord 봇 토큰으로 채널에 직접 발송 (게이트웨이 불필요, REST).
    카드 이미지가 있으면 이미지만, 없으면 텍스트 폴백. webhook URL 불필요."""
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token or not channel_id:
        return {"status": "skipped"}
    if dry_run():
        return {"status": "dry_run"}
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}"}
    try:
        import httpx
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                r = httpx.post(url, headers=headers,
                               files={"file": (os.path.basename(image_path), f, "image/png")},
                               timeout=15)
        else:
            r = httpx.post(url, headers=headers, json={"content": text}, timeout=15)
        r.raise_for_status()
        return {"status": "sent"}
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "error": str(e)}
