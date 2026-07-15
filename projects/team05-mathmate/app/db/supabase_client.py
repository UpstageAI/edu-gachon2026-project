"""Supabase REST 클라이언트 (users/attempts 진척도 저장용)."""
from functools import lru_cache
from supabase import create_client, Client
from app.core import config


@lru_cache
def get_client() -> Client:
    return create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
