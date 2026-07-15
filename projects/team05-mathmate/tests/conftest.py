"""테스트는 API 키 유무와 상관없이 Mock 규칙으로 결정론적으로 실행 (네트워크 호출 방지)."""
import pytest
from app.core import config

# problem_repo는 모듈 import 시점에 문제은행을 한 번만 메모리에 올린다.
# .env에 실제 Supabase 키가 있으면 테스트 모듈(들이 problem_repo.get_problem("arith_001") 등을
# 모듈 최상단에서 호출)이 import되는 순간 이미 Supabase의 실제 문제로 채워져,
# 아래 force_mock 픽스처(테스트 함수 실행 시점에만 적용)로는 되돌릴 수 없다.
# 그래서 테스트 모듈이 import되기 전에 여기서 미리 로컬 JSON(픽스처 포함)으로 재적재해둔다.
config.USE_SUPABASE = False
from app.repositories import problem_repo  # noqa: E402
problem_repo.reload()


@pytest.fixture(autouse=True)
def force_mock(monkeypatch):
    monkeypatch.setattr(config, "USE_LLM", False)
    # 테스트는 네트워크(Supabase) 없이 로컬 JSON으로만 결정론적으로 실행
    monkeypatch.setattr(config, "USE_SUPABASE", False)


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    """테이블 하나(예: users, attempts)의 인메모리 저장소. id는 1부터 자동 증가."""
    def __init__(self):
        self.rows: list[dict] = []
        self._next_id = 1

    def new_id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value


class _FakeQuery:
    """supabase-py의 .table().select().eq()...execute() 체이닝을 흉내 낸다."""
    def __init__(self, table: _FakeTable):
        self._table = table
        self._filters: dict = {}
        self._limit = None
        self._mode = "select"
        self._payload = None

    def select(self, *_args, **_kwargs):
        self._mode = "select"
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def limit(self, n):
        self._limit = n
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._mode = "update"
        self._payload = payload
        return self

    def delete(self):
        self._mode = "delete"
        return self

    def _matched(self):
        return [r for r in self._table.rows if all(r.get(k) == v for k, v in self._filters.items())]

    def execute(self):
        if self._mode == "insert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            created = []
            for p in payloads:
                row = dict(p)
                row.setdefault("id", self._table.new_id())
                self._table.rows.append(row)
                created.append(row)
            return _FakeResult(created)

        matched = self._matched()
        if self._mode == "update":
            for row in matched:
                row.update(self._payload)
            return _FakeResult(matched)
        if self._mode == "delete":
            for row in matched:
                self._table.rows.remove(row)
            return _FakeResult(matched)

        if self._limit is not None:
            matched = matched[: self._limit]
        return _FakeResult(matched)


class FakeSupabaseClient:
    """user_repo/attempt_repo가 기대하는 최소한의 supabase-py 인터페이스만 구현한 테스트 더블."""
    def __init__(self):
        self._tables: dict[str, _FakeTable] = {}

    def table(self, name: str) -> _FakeQuery:
        self._tables.setdefault(name, _FakeTable())
        return _FakeQuery(self._tables[name])


@pytest.fixture
def fake_supabase(monkeypatch):
    """user_repo/attempt_repo가 실제 Supabase 대신 이 인메모리 더블을 쓰게 한다."""
    from app.repositories import user_repo, attempt_repo

    client = FakeSupabaseClient()
    monkeypatch.setattr(user_repo, "get_client", lambda: client)
    monkeypatch.setattr(attempt_repo, "get_client", lambda: client)
    return client
