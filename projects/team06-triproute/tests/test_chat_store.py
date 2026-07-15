from types import SimpleNamespace

import app.services.chat_store as chat_store


class FakeQuery:
    """
    supabase-py의 `.table(...).select(...).eq(...).order(...).limit(...).execute()`
    체이닝을 흉내내는 가짜 빌더. 호출된 조건(filters)을 기록해두고, execute() 시점에
    미리 준비된 rows에 eq 필터만 적용해서 돌려준다(테스트에 필요한 만큼만 단순 구현).
    """

    def __init__(self, table, rows, recorder):
        self.table_name = table
        self._all_rows = rows
        self._filters = {}
        self._recorder = recorder
        self._insert_row = None
        self._update_row = None
        self._op = "select"

    def select(self, *_args, **_kwargs):
        self._op = "select"
        return self

    def insert(self, row):
        self._op = "insert"
        self._insert_row = row
        return self

    def update(self, row):
        self._op = "update"
        self._update_row = row
        return self

    def eq(self, key, value):
        self._filters[key] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        self._recorder.append(
            {
                "table": self.table_name,
                "op": self._op,
                "filters": dict(self._filters),
                "row": self._insert_row or self._update_row,
            }
        )

        if self._op == "insert":
            new_row = {"id": "generated-id", **self._insert_row}
            self._all_rows.append(new_row)
            return SimpleNamespace(data=[new_row])

        if self._op == "update":
            matched = [
                row
                for row in self._all_rows
                if all(row.get(k) == v for k, v in self._filters.items())
            ]
            for row in matched:
                row.update(self._update_row)
            return SimpleNamespace(data=matched)

        matched = [
            row
            for row in self._all_rows
            if all(row.get(k) == v for k, v in self._filters.items())
        ]
        return SimpleNamespace(data=matched)


class FakeClient:
    def __init__(self, tables, recorder):
        self._tables = tables
        self._recorder = recorder

    def table(self, name):
        return FakeQuery(name, self._tables.setdefault(name, []), self._recorder)


def _install_fake_client(monkeypatch, tables=None):
    tables = tables if tables is not None else {}
    recorder = []
    monkeypatch.setattr(chat_store, "get_client", lambda: FakeClient(tables, recorder))
    return tables, recorder


def test_create_session_inserts_row(monkeypatch):
    tables, recorder = _install_fake_client(monkeypatch)

    result = chat_store.create_session("user-1", title="강릉 여행")

    assert result["user_id"] == "user-1"
    assert result["title"] == "강릉 여행"
    assert recorder[0]["op"] == "insert"


def test_list_recent_sessions_filters_by_user(monkeypatch):
    tables, _ = _install_fake_client(
        monkeypatch,
        tables={
            "chat_sessions": [
                {"id": "s1", "user_id": "user-1", "title": "A"},
                {"id": "s2", "user_id": "user-2", "title": "B"},
            ]
        },
    )

    result = chat_store.list_recent_sessions("user-1")

    assert [row["id"] for row in result] == ["s1"]


def test_get_session_messages_rejects_other_users_session(monkeypatch):
    tables, _ = _install_fake_client(
        monkeypatch,
        tables={
            "chat_sessions": [{"id": "s1", "user_id": "owner"}],
            "chat_messages": [{"id": "m1", "session_id": "s1", "content": "hi"}],
        },
    )

    # owner가 아닌 다른 user_id로 조회하면 빈 목록을 반환해야 한다(소유권 미검증 방지)
    result = chat_store.get_session_messages("s1", "someone-else")

    assert result == []


def test_get_session_messages_returns_messages_for_owner(monkeypatch):
    tables, _ = _install_fake_client(
        monkeypatch,
        tables={
            "chat_sessions": [{"id": "s1", "user_id": "owner"}],
            "chat_messages": [{"id": "m1", "session_id": "s1", "content": "hi"}],
        },
    )

    result = chat_store.get_session_messages("s1", "owner")

    assert result == [{"id": "m1", "session_id": "s1", "content": "hi"}]


def test_append_message_also_bumps_session_updated_at(monkeypatch):
    tables, recorder = _install_fake_client(
        monkeypatch,
        tables={"chat_sessions": [{"id": "s1", "user_id": "owner", "updated_at": "old"}]},
    )

    chat_store.append_message("s1", "owner", "user", "안녕")

    ops = [(entry["table"], entry["op"]) for entry in recorder]
    assert ("chat_messages", "insert") in ops
    assert ("chat_sessions", "update") in ops
    assert tables["chat_sessions"][0]["updated_at"] != "old"


def test_append_message_rejects_other_users_session(monkeypatch):
    tables, _ = _install_fake_client(
        monkeypatch,
        tables={"chat_sessions": [{"id": "s1", "user_id": "owner"}]},
    )

    try:
        chat_store.append_message("s1", "someone-else", "user", "안녕")
        assert False, "should have raised PermissionError"
    except PermissionError:
        pass


def test_update_session_condition_summary(monkeypatch):
    tables, _ = _install_fake_client(
        monkeypatch,
        tables={"chat_sessions": [{"id": "s1", "user_id": "owner"}]},
    )

    chat_store.update_session_condition_summary("s1", "owner", {"city": "강릉"})

    assert tables["chat_sessions"][0]["last_condition_summary"] == {"city": "강릉"}
