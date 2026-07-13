"""세션 히스토리 저장소 — 로그인 없이 "한 접속 = 세션"을 흉내낸다.

프론트가 접속당 UUID(session_id)를 생성해 매 요청에 실어 보내면, 서버는 그 키로
최근 턴(질문/SQL/요약)을 in-memory 로 보관한다. 후속질문 병합(query_normalizer)과
버튼형 후속질문 생성(query_service.suggest_followups)이 이 히스토리를 쓴다.

ponytail: 프로세스 메모리 저장이라 uvicorn 워커를 2개 이상 쓰면 세션이 워커마다
갈라진다. 지금은 단일 워커 전제 — 워커를 늘리게 되면 Redis 등 외부 저장소로 교체.
"""
from __future__ import annotations

import threading
import time

_TTL_S = 1800  # 세션 유휴 30분이면 만료
_MAX_TURNS = 5  # 턴당 히스토리는 최근 5개만 유지
_MAX_SESSIONS = 10_000  # 동시 보유 세션 상한 (인증 없는 구조라 무한 생성 방어)


class SessionStore:
    def __init__(self, ttl_s: float = _TTL_S, max_turns: int = _MAX_TURNS,
                 max_sessions: int = _MAX_SESSIONS) -> None:
        if max_sessions <= 0:
            raise ValueError("max_sessions 는 1 이상이어야 합니다")
        self._ttl_s = ttl_s
        self._max_turns = max_turns
        self._max_sessions = max_sessions
        self._sessions: dict[str, tuple[float, list[dict]]] = {}  # id -> (expires_at, turns)
        self._lock = threading.Lock()

    def get_history(self, session_id: str | None) -> list[dict]:
        """session_id 의 최근 턴 목록. 없거나 만료됐으면 빈 리스트."""
        if not session_id:
            return []
        with self._lock:
            self._evict_expired()
            entry = self._sessions.get(session_id)
            return list(entry[1]) if entry else []

    def append_turn(self, session_id: str | None, question: str, sql: str, summary: str) -> None:
        """성공한 턴 1개를 히스토리에 추가하고 TTL 을 갱신한다. session_id 없으면 no-op."""
        if not session_id:
            return
        with self._lock:
            self._evict_expired()
            if session_id not in self._sessions and len(self._sessions) >= self._max_sessions:
                oldest = min(self._sessions, key=lambda k: self._sessions[k][0])
                del self._sessions[oldest]  # 상한 도달 시 만료가 가장 임박한 세션부터 축출
            _, turns = self._sessions.get(session_id, (0.0, []))
            turns = [*turns, {"q": question, "sql": sql, "result_summary": summary}][-self._max_turns:]
            self._sessions[session_id] = (time.time() + self._ttl_s, turns)

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [sid for sid, (exp, _) in self._sessions.items() if exp < now]
        for sid in expired:
            del self._sessions[sid]


session_store = SessionStore()
