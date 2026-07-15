from app.data.repositories import recipe_repository


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


class _FakeMatchQuery:
    def __init__(self, all_rows):
        self._all_rows = all_rows
        self._start = 0
        self._end = None

    def select(self, *_args, **_kwargs):
        return self

    def in_(self, _column, _values):
        return self

    def range(self, start, end):
        self._start = start
        self._end = end
        return self

    def execute(self):
        return _FakeResponse(self._all_rows[self._start : self._end + 1])


class _FakeMatchSupabase:
    def __init__(self, all_rows):
        self._all_rows = all_rows
        self.call_count = 0

    def table(self, _name):
        self.call_count += 1
        return _FakeMatchQuery(self._all_rows)


def test_find_recipe_ingredient_matches_returns_empty_for_no_ids():
    assert recipe_repository.find_recipe_ingredient_matches([]) == {}


def test_find_recipe_ingredient_matches_paginates_past_page_size(monkeypatch):
    """실제 버그 재현: 소금처럼 매칭 행이 많은 재료가 섞이면 전체 행 수가 PostgREST
    기본 응답 상한(1000행)을 넘길 수 있는데, 이전에는 .range() 없이 단일 조회만 해서
    감자/우유처럼 뒤쪽에 있는 재료의 매칭이 통째로 잘려나갔다. 페이지 크기를 2로
    좁혀서 5개 행이 여러 페이지에 걸쳐도 전부 모이는지 확인한다."""
    monkeypatch.setattr(recipe_repository, "_RECIPE_INGREDIENT_MATCH_PAGE_SIZE", 2)
    rows = [
        {"recipe_id": "r1", "ingredient_id": "salt"},
        {"recipe_id": "r2", "ingredient_id": "salt"},
        {"recipe_id": "r3", "ingredient_id": "potato"},
        {"recipe_id": "r4", "ingredient_id": "milk"},
        {"recipe_id": "r5", "ingredient_id": "potato"},
    ]
    fake_supabase = _FakeMatchSupabase(rows)
    monkeypatch.setattr(recipe_repository, "get_supabase", lambda: fake_supabase)

    result = recipe_repository.find_recipe_ingredient_matches(["salt", "potato", "milk"])

    assert result == {
        "r1": ["salt"],
        "r2": ["salt"],
        "r3": ["potato"],
        "r4": ["milk"],
        "r5": ["potato"],
    }
    # 페이지 크기 2로 5개 행 -> 2+2+1행씩 3번 조회, 마지막 페이지가 페이지 크기보다
    # 작아서(1 < 2) 멈춘다.
    assert fake_supabase.call_count == 3


class _FakeCountQuery:
    def __init__(self, count):
        self._count = count

    def select(self, *_args, count=None, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return _FakeResponse([], count=self._count)


class _FakeCountSupabase:
    def __init__(self, counts_by_call):
        self._counts = list(counts_by_call)
        self.call_count = 0

    def table(self, _name):
        count = self._counts[self.call_count]
        self.call_count += 1
        return _FakeCountQuery(count)


def test_get_ingredient_document_frequency_queries_and_caches_uncached_ids(monkeypatch):
    fake_redis = _FakeRedis()
    fake_supabase = _FakeCountSupabase([2268, 416])
    monkeypatch.setattr(recipe_repository, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(recipe_repository, "get_supabase", lambda: fake_supabase)

    result = recipe_repository.get_ingredient_document_frequency(["salt", "potato"])

    assert result == {"salt": 2268, "potato": 416}
    assert fake_supabase.call_count == 2
    assert fake_redis.store["ingredient:df:salt"] == 2268
    assert fake_redis.store["ingredient:df:potato"] == 416


def test_get_ingredient_document_frequency_uses_cache_for_already_cached_ids(monkeypatch):
    fake_redis = _FakeRedis()
    fake_redis.store["ingredient:df:salt"] = 2268
    fake_supabase = _FakeCountSupabase([416])  # potato만 조회돼야 함
    monkeypatch.setattr(recipe_repository, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(recipe_repository, "get_supabase", lambda: fake_supabase)

    result = recipe_repository.get_ingredient_document_frequency(["salt", "potato"])

    assert result == {"salt": 2268, "potato": 416}
    assert fake_supabase.call_count == 1


def test_get_ingredient_document_frequency_returns_empty_for_no_ids():
    assert recipe_repository.get_ingredient_document_frequency([]) == {}


def test_get_total_recipe_count_uses_cache_on_second_call(monkeypatch):
    fake_redis = _FakeRedis()
    fake_supabase = _FakeCountSupabase([8082])
    monkeypatch.setattr(recipe_repository, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(recipe_repository, "get_supabase", lambda: fake_supabase)

    first = recipe_repository.get_total_recipe_count()
    second = recipe_repository.get_total_recipe_count()

    assert first == second == 8082
    assert fake_supabase.call_count == 1
