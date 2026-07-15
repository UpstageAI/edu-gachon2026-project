"""Nano Banana (Gemini image) 이미지 생성 툴 — Tool 레이어.
   GEMINI_API_KEY 없거나 FINBRIEF_IMAGE_STUB=1 이면 None(플레이스홀더 유지).
   저장은 로컬(out_llm/). 프로덕션은 Supabase Storage 로 교체 예정."""
from __future__ import annotations

import base64
import os
from pydantic import BaseModel

IMAGE_MODEL = os.getenv("FINBRIEF_IMAGE_MODEL", "gemini-3.1-flash-lite-image")


class ImageAsset(BaseModel):
    path: str | None = None
    url: str | None = None
    model: str
    prompt: str
    mime_type: str = "image/png"


def image_enabled() -> bool:
    return bool(os.getenv("GEMINI_API_KEY")) and os.getenv("FINBRIEF_IMAGE_STUB") != "1"


def _call_gemini(prompt: str) -> bytes:
    """실제 Nano Banana 호출 -> PNG bytes. (google-genai)"""
    from google import genai  # lazy import
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    resp = client.models.generate_content(model=IMAGE_MODEL, contents=prompt)
    for part in resp.candidates[0].content.parts:
        inline = getattr(part, "inline_data", None)
        if inline and getattr(inline, "data", None):
            data = inline.data
            return data if isinstance(data, bytes) else base64.b64decode(data)
    raise RuntimeError("no image in Gemini response")


def generate_image(prompt: str, out_dir: str, name: str) -> ImageAsset | None:
    if not image_enabled():
        return None
    png = _call_gemini(prompt)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{name}.png")
    with open(path, "wb") as f:
        f.write(png)
    return ImageAsset(path=path, model=IMAGE_MODEL, prompt=prompt)
