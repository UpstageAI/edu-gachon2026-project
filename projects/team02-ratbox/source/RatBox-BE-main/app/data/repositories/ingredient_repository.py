import json

from app.data.redis_client import get_redis
from app.data.supabase_client import get_supabase

_ALL_CATEGORIES_CACHE_KEY = "ingredients:categories"
_ALL_CATEGORIES_CACHE_TTL_SECONDS = 1800
_CATEGORY_PAGE_SIZE = 1000


def get_ingredient_names_by_ids(ingredient_ids: list[str]) -> list[str]:
    if not ingredient_ids:
        return []

    supabase = get_supabase()
    response = (
        supabase.table("ingredients_master").select("name").in_("id", ingredient_ids).execute()
    )
    return [row["name"] for row in response.data]


def get_ingredient_categories_by_names(names: list[str]) -> dict[str, str | None]:
    """재료 이름 -> 카테고리명 매핑. FE가 부족/보유 재료를 카테고리별로 묶어 보여줄 때 쓴다."""
    if not names:
        return {}

    supabase = get_supabase()
    response = (
        supabase.table("ingredients_master")
        .select("name, ingredients_category(name)")
        .in_("name", names)
        .execute()
    )
    return {
        row["name"]: (row["ingredients_category"] or {}).get("name") for row in response.data
    }


def _select_categories_page(offset: int, count: str | None = None):
    supabase = get_supabase()
    query = supabase.table("ingredients_category").select("id, name", count=count)
    return query.order("name").range(offset, offset + _CATEGORY_PAGE_SIZE - 1).execute()


def _fetch_all_categories_from_db() -> list[dict]:
    """Supabase(PostgREST)는 한 번의 조회당 최대 _CATEGORY_PAGE_SIZE개로 응답을 제한하므로,
    첫 페이지에서 정확한 전체 개수(count)를 받아 남은 페이지 수를 미리 계산한다."""
    first = _select_categories_page(0, count="exact")
    rows: list[dict] = list(first.data)

    for offset in range(_CATEGORY_PAGE_SIZE, first.count or 0, _CATEGORY_PAGE_SIZE):
        rows.extend(_select_categories_page(offset).data)
    return rows


def find_all_categories() -> list[dict]:
    """재료 카테고리는 거의 바뀌지 않는 참조 데이터라 Redis에 캐싱해 재조회를 건너뛴다."""
    redis_client = get_redis()
    cached = redis_client.get(_ALL_CATEGORIES_CACHE_KEY)
    if cached is not None:
        return json.loads(cached)

    rows = _fetch_all_categories_from_db()

    redis_client.set(
        _ALL_CATEGORIES_CACHE_KEY, json.dumps(rows), ex=_ALL_CATEGORIES_CACHE_TTL_SECONDS
    )
    return rows


def find_ingredients_by_category_id(category_id: str) -> list[dict]:
    supabase = get_supabase()
    response = (
        supabase.table("ingredients_master")
        .select("id, name, description, allergen_master(id, allergen_name, category)")
        .eq("category_id", category_id)
        .execute()
    )
    return response.data


def resolve_ingredient_id(name: str) -> int | None:
    supabase = get_supabase()

    response = supabase.table("ingredients_master").select("id").eq("name", name).execute()
    if response.data:
        return response.data[0]["id"]

    syn_response = (
        supabase.table("ingredient_synonyms")
        .select("ingredient_id")
        .eq("synonym_name", name)
        .execute()
    )
    if syn_response.data:
        return syn_response.data[0]["ingredient_id"]

    return None
