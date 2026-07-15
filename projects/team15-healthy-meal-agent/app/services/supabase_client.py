"""
app/services/supabase_client.py
Supabase 클라이언트 생성 래퍼.
환경변수(SUPABASE_URL, SUPABASE_KEY)를 읽어 클라이언트를 한 번 만들고 캐시한다.
"""

import os

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

_CLIENT: Client | None = None


def get_client() -> Client:
    """Supabase 클라이언트 반환 (한 번 생성 후 캐시). 환경변수 누락 시 명확히 에러."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY 환경변수가 없습니다. .env를 확인하세요.")

    _CLIENT = create_client(url, key)
    return _CLIENT
