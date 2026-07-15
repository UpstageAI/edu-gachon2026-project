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


def test_max_sessions_evicts_oldest() -> None:
    store = SessionStore(max_sessions=2)
    store.append_turn("s1", "q", "", "")
    store.append_turn("s2", "q", "", "")
    store.append_turn("s3", "q", "", "")  # 상한 초과 → 가장 오래된(s1) 축출
    assert store.get_history("s1") == []
    assert store.get_history("s2") != []
    assert store.get_history("s3") != []
    assert len(store._sessions) == 2


def test_max_sessions_updating_existing_does_not_evict() -> None:
    store = SessionStore(max_sessions=2)
    store.append_turn("s1", "q0", "", "")
    store.append_turn("s2", "q0", "", "")
    store.append_turn("s1", "q1", "", "")  # 기존 세션 갱신은 상한에 안 걸림
    assert len(store._sessions) == 2
    assert [h["q"] for h in store.get_history("s1")] == ["q0", "q1"]


def test_max_sessions_rejects_non_positive() -> None:
    for bad in (0, -1):
        try:
            SessionStore(max_sessions=bad)
            raise AssertionError(f"max_sessions={bad} 가 거부되지 않음")
        except ValueError:
            pass


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all session_store checks passed")
