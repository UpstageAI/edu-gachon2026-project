import json

from app.data.redis_client import get_redis
from app.data.supabase_client import get_supabase

_ALL_ALLERGENS_CACHE_KEY = "allergens:all"
_ALL_ALLERGENS_CACHE_TTL_SECONDS = 1800


def get_allergen_names_by_ids(allergen_ids: list[str]) -> list[str]:
    if not allergen_ids:
        return []

    supabase = get_supabase()
    response = (
        supabase.table("allergen_master").select("allergen_name").in_("id", allergen_ids).execute()
    )
    return [row["allergen_name"] for row in response.data]


def find_all_allergens() -> list[dict]:
    """알레르기 마스터는 거의 바뀌지 않는 참조 데이터라 Redis에 캐싱해 재조회를 건너뛴다."""
    redis_client = get_redis()
    cached = redis_client.get(_ALL_ALLERGENS_CACHE_KEY)
    if cached is not None:
        return json.loads(cached)

    supabase = get_supabase()
    response = supabase.table("allergen_master").select("*").order("category").execute()

    redis_client.set(
        _ALL_ALLERGENS_CACHE_KEY, json.dumps(response.data), ex=_ALL_ALLERGENS_CACHE_TTL_SECONDS
    )
    return response.data


def find_allergens_by_ids(allergen_ids: list[str]) -> list[dict]:
    if not allergen_ids:
        return []
    supabase = get_supabase()
    response = supabase.table("allergen_master").select("*").in_("id", allergen_ids).execute()
    return response.data
