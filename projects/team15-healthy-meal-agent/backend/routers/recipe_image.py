"""
backend/routers/recipe_image.py
레시피 이미지 프록시 + 디스크 캐시.

왜 필요한가: 원본(foodsafetykorea)은 한 페이지에서 이미지 수십 장을 동시에 받으면
IP를 rate-limit으로 막는다(Connection refused). 그래서 우리 백엔드가 원본을 '한 번만'
받아 디스크에 저장하고, 이후 요청은 캐시에서 즉시 응답한다.
→ 브라우저는 우리 서버에서만 로드하므로 rate-limit이 안 걸리고, 단계별 사진을 모두
  순서대로 보여줄 수 있다.

보안: 임의 URL 프록시는 SSRF 위험 → 원본 도메인 화이트리스트로만 허용한다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

router = APIRouter(prefix="/api/v1", tags=["recipe-image"])

# 원본 이미지 호스트 화이트리스트 (SSRF 방지). 삼삼한밥상 레시피 사진 출처.
_ALLOWED_HOSTS = {"www.foodsafetykorea.go.kr", "foodsafetykorea.go.kr"}

# 디스크 캐시 위치. 프로젝트 루트 아래 .cache/recipe_img/ (gitignore 대상).
_CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "recipe_img"


def _cache_path(url: str) -> Path:
    """URL → 캐시 파일 경로(내용 무관 고정 이름). 확장자는 png로 통일(원본이 png)."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return _CACHE_DIR / f"{digest}.png"


def _normalize(url: str) -> str:
    """http:// → https:// 로 통일(원본이 http로 오지만 실제 서비스는 https)."""
    return "https://" + url[len("http://") :] if url.startswith("http://") else url


@router.get("/recipe-image")
def recipe_image(url: str = Query(..., description="원본 레시피 이미지 URL")) -> Response:
    """원본 이미지를 프록시하고 디스크에 캐시한다. 화이트리스트 호스트만 허용."""
    norm = _normalize(url)
    host = urlparse(norm).hostname or ""
    if host not in _ALLOWED_HOSTS:
        raise HTTPException(status_code=400, detail="허용되지 않은 이미지 호스트입니다.")

    cached = _cache_path(norm)
    if cached.exists():
        # 캐시 히트 → 즉시 파일 응답(원본 서버 부담 0, rate-limit 회피)
        return FileResponse(cached, media_type="image/png")

    try:
        resp = httpx.get(norm, timeout=15, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        # 원본이 일시적으로 막혀도(rate-limit 등) 500 대신 502로 알리고 캐시엔 안 남긴다.
        raise HTTPException(status_code=502, detail=f"원본 이미지 로드 실패: {exc}") from exc

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(resp.content)
    media = resp.headers.get("content-type", "image/png").split(";")[0]
    return Response(content=resp.content, media_type=media)
