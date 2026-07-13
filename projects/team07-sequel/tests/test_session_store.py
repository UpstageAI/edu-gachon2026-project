"""session_store 자체 점검 — TTL 만료 · 턴 개수 상한 · session_id 없음 처리.

프레임워크 없이 assert 로만 검증(프로젝트 관례, eval_linker.py 참고).

실행:  uv run python -m tests.test_session_store
"""
from __future__ import annotations

import time

from app.core.session_store import SessionStore


def test_no_session_id_is_noop() -> None:
    store = SessionStore()
    assert store.get_history(None) == []
    store.append_turn(None, "q", "sql", "sum")
    assert store.get_history(None) == []


def test_unknown_session_returns_empty() -> None:
    store = SessionStore()
    assert store.get_history("nope") == []


def test_append_and_get() -> None:
    store = SessionStore()
    store.append_turn("s1", "q1", "sql1", "sum1")
    assert store.get_history("s1") == [{"q": "q1", "sql": "sql1", "result_summary": "sum1"}]


def test_max_turns_caps_history() -> None:
    store = SessionStore(max_turns=2)
    for i in range(4):
        store.append_turn("s1", f"q{i}", "", "")
    hist = store.get_history("s1")
    assert [h["q"] for h in hist] == ["q2", "q3"]


def test_ttl_expiry() -> None:
    store = SessionStore(ttl_s=0.05)
    store.append_turn("s1", "q1", "sql1", "sum1")
    assert store.get_history("s1") != []
    time.sleep(0.1)
    assert store.get_history("s1") == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all session_store checks passed")
