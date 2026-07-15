import json

from app.data.repositories import ingredient_repository


class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.ex_by_key = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value
        self.ex_by_key[key] = ex


class _FakeResponse:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _FakeQuery:
    def __init__(self, data):
        self._full_data = data
        self._data = data
        self._count_requested = False

    def select(self, *_args, count=None, **_kwargs):
        self._count_requested = count == "exact"
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, start, end):
        self._data = self._full_data[start : end + 1]
        return self

    def execute(self):
        count = len(self._full_data) if self._count_requested else None
        return _FakeResponse(self._data, count=count)


class _FakeSupabase:
    def __init__(self, data):
        self._data = data
        self.call_count = 0

    def table(self, _name):
        self.call_count += 1
        return _FakeQuery(self._data)


def _patch_clients(monkeypatch, redis_client, supabase_client):
    monkeypatch.setattr(ingredient_repository, "get_redis", lambda: redis_client)
    monkeypatch.setattr(ingredient_repository, "get_supabase", lambda: supabase_client)


def test_find_all_categories_uses_cache_on_second_call(monkeypatch):
    fake_redis = _FakeRedis()
    fake_supabase = _FakeSupabase([{"id": "1", "name": "카레"}, {"id": "2", "name": "마늘"}])
    _patch_clients(monkeypatch, fake_redis, fake_supabase)

    first = ingredient_repository.find_all_categories()
    second = ingredient_repository.find_all_categories()

    assert first == second == [{"id": "1", "name": "카레"}, {"id": "2", "name": "마늘"}]
    # 첫 호출만 DB를 조회하고(페이지 1개), 두 번째 호출은 캐시에서 바로 반환된다.
    assert fake_supabase.call_count == 1


def test_find_all_categories_paginates_past_page_size(monkeypatch):
    monkeypatch.setattr(ingredient_repository, "_CATEGORY_PAGE_SIZE", 2)
    rows = [{"id": str(i), "name": f"카테고리{i}"} for i in range(5)]
    fake_redis = _FakeRedis()
    fake_supabase = _FakeSupabase(rows)
    _patch_clients(monkeypatch, fake_redis, fake_supabase)

    result = ingredient_repository.find_all_categories()

    assert result == rows
    # 첫 페이지에서 count="exact"로 전체 개수(5)를 받아, 남은 페이지 수(2개)만큼만 추가 조회한다.
    assert fake_supabase.call_count == 3


def test_find_all_categories_stores_cache_with_ttl(monkeypatch):
    fake_redis = _FakeRedis()
    fake_supabase = _FakeSupabase([{"id": "1", "name": "카레"}])
    _patch_clients(monkeypatch, fake_redis, fake_supabase)

    ingredient_repository.find_all_categories()

    cache_key = ingredient_repository._ALL_CATEGORIES_CACHE_KEY
    expected_ttl = ingredient_repository._ALL_CATEGORIES_CACHE_TTL_SECONDS
    assert json.loads(fake_redis.store[cache_key]) == [{"id": "1", "name": "카레"}]
    assert fake_redis.ex_by_key[cache_key] == expected_ttl


class _FakeInQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *_args, **_kwargs):
        return self

    def in_(self, _column, _values):
        return self

    def execute(self):
        return _FakeResponse(self._data)


class _FakeSupabaseIn:
    def __init__(self, data):
        self._data = data

    def table(self, _name):
        return _FakeInQuery(self._data)


def test_get_ingredient_categories_by_names_maps_name_to_category(monkeypatch):
    fake_supabase = _FakeSupabaseIn(
        [
            {"name": "대파", "ingredients_category": {"name": "채소류"}},
            {"name": "소금", "ingredients_category": None},
        ]
    )
    monkeypatch.setattr(ingredient_repository, "get_supabase", lambda: fake_supabase)

    result = ingredient_repository.get_ingredient_categories_by_names(["대파", "소금"])

    assert result == {"대파": "채소류", "소금": None}


def test_get_ingredient_categories_by_names_returns_empty_for_no_names():
    assert ingredient_repository.get_ingredient_categories_by_names([]) == {}
