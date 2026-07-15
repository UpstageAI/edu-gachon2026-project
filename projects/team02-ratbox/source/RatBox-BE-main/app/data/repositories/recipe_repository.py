from app.data.redis_client import get_redis
from app.data.supabase_client import execute_with_retry, get_supabase

_DOCUMENT_FREQUENCY_CACHE_TTL_SECONDS = 1800
_TOTAL_RECIPE_COUNT_CACHE_KEY = "recipes:total_count"
_RECIPE_INGREDIENT_MATCH_PAGE_SIZE = 1000


def find_recipe_ingredient_matches(ingredient_ids: list[str]) -> dict[str, list[str]]:
    """ingredient_ids 중 하나라도 쓰이는 레시피별로, 실제 겹치는 ingredient_id 목록을 묶어 반환한다.

    후보 recipe_id마다 재료 목록을 왕복 쿼리로 하나씩 가져오면(N+1) 후보가 많을 때
    지연이 누적되므로, 매칭 계산에 필요한 (recipe_id, ingredient_id) 쌍을 애초에
    ingredient_ids(사용자가 고른 소수의 재료) 기준 단 한 번의 쿼리로 가져온다. recipe_id
    기준으로 필터링하면 후보가 많을 때 쿼리 URL이 너무 길어질 수 있어 피한다.

    소금처럼 매칭 행이 많은 재료가 ingredient_ids에 섞이면 전체 행 수가 PostgREST
    기본 응답 상한(1000행)을 넘길 수 있다 - 응답이 조용히 잘리면 소금 매칭 행만 가득
    채워지고 감자/우유처럼 실제로 중요한 재료의 매칭이 통째로 사라지는 식으로 결과가
    왜곡된다 (재료 3개 중 2개의 매칭이 전부 유실됐던 실제 사례로 확인됨). .range()로
    끝까지 페이지네이션해 전체 행을 받는다."""
    if not ingredient_ids:
        return {}

    supabase = get_supabase()
    matches: dict[str, list[str]] = {}
    offset = 0
    while True:
        response = execute_with_retry(
            supabase.table("recipe_ingredients")
            .select("recipe_id, ingredient_id")
            .in_("ingredient_id", ingredient_ids)
            .range(offset, offset + _RECIPE_INGREDIENT_MATCH_PAGE_SIZE - 1)
        )
        rows = response.data
        for row in rows:
            matches.setdefault(row["recipe_id"], []).append(row["ingredient_id"])
        if len(rows) < _RECIPE_INGREDIENT_MATCH_PAGE_SIZE:
            break
        offset += _RECIPE_INGREDIENT_MATCH_PAGE_SIZE
    return matches


def get_recipes_by_ids(recipe_ids: list[str]) -> list[dict]:
    if not recipe_ids:
        return []

    supabase = get_supabase()
    response = execute_with_retry(
        supabase.table("recipes").select("id, name, cooking_time").in_("id", recipe_ids)
    )
    return response.data


def get_recipe_by_id(recipe_id: str) -> dict | None:
    supabase = get_supabase()
    response = execute_with_retry(
        supabase.table("recipes")
        .select("id, name, cooking_time, difficulty, category, cooking_method")
        .eq("id", recipe_id)
    )
    return response.data[0] if response.data else None


def get_ingredient_document_frequency(ingredient_ids: list[str]) -> dict[str, int]:
    """ingredient_id별로 몇 개의 레시피에 쓰이는지(document frequency). 소금처럼 거의
    모든 레시피에 들어가는 재료와 감자처럼 상대적으로 드문 재료를 구분해 매칭 가중치를
    매기는 근거 데이터 - search_service의 재료 가중치 스코어링에서 쓴다.

    재료 id를 한 번에 묶어서 조회하면 소금처럼 레시피가 많은 재료가 섞였을 때 결과 행
    수가 PostgREST 기본 응답 상한(1000행)을 넘겨 조용히 잘릴 수 있어, id 하나씩
    count="exact"로 정확한 총량만 받는다. 사용자가 고른 소수(보통 10개 이하)의
    재료에 대해서만 호출하므로 요청당 비용은 작고, 값 자체도 자주 안 바뀌는 참조성
    데이터라 Redis에 캐싱한다."""
    if not ingredient_ids:
        return {}

    redis_client = get_redis()
    supabase = get_supabase()
    result: dict[str, int] = {}
    uncached_ids = []
    for ingredient_id in ingredient_ids:
        cached = redis_client.get(f"ingredient:df:{ingredient_id}")
        if cached is None:
            uncached_ids.append(ingredient_id)
        else:
            result[ingredient_id] = int(cached)

    for ingredient_id in uncached_ids:
        response = execute_with_retry(
            supabase.table("recipe_ingredients")
            .select("recipe_id", count="exact")
            .eq("ingredient_id", ingredient_id)
            .limit(1)
        )
        count = response.count or 0
        result[ingredient_id] = count
        redis_client.set(
            f"ingredient:df:{ingredient_id}", count, ex=_DOCUMENT_FREQUENCY_CACHE_TTL_SECONDS
        )

    return result


def get_total_recipe_count() -> int:
    redis_client = get_redis()
    cached = redis_client.get(_TOTAL_RECIPE_COUNT_CACHE_KEY)
    if cached is not None:
        return int(cached)

    supabase = get_supabase()
    response = execute_with_retry(supabase.table("recipes").select("id", count="exact").limit(1))
    count = response.count or 0
    redis_client.set(
        _TOTAL_RECIPE_COUNT_CACHE_KEY, count, ex=_DOCUMENT_FREQUENCY_CACHE_TTL_SECONDS
    )
    return count


def get_recipe_ingredient_names(recipe_id: str) -> list[dict]:
    supabase = get_supabase()
    response = execute_with_retry(
        supabase.table("recipe_ingredients")
        .select("is_required, ingredients_master(name)")
        .eq("recipe_id", recipe_id)
    )
    return [
        {"name": row["ingredients_master"]["name"], "is_required": row["is_required"]}
        for row in response.data
    ]
