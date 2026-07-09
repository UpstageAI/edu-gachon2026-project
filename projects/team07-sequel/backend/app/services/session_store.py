"""대화 세션/히스토리 저장소.

"그럼 그 중에 카테고리별로 나눠줘" 같은 후속 질문을 지원하기 위해,
session_id 기준으로 이전 질문·SQL·요약을 잠깐 저장해둔다.

지금은 프로세스 메모리에 딕셔너리로 저장하는 가장 단순한 구현이다.
부트캠프 규모(단일 Cloud Run 인스턴스, 짧은 프로젝트 기간)에는 충분하며,
나중에 다중 인스턴스로 스케일하게 되면 Redis 등 외부 저장소로 교체하면 된다.
"""

from typing import TypedDict

_MAX_HISTORY_PER_SESSION = 10


class Turn(TypedDict):
    question: str
    sql: str
    summary: str


_sessions: dict[str, list[Turn]] = {}


def get_history(session_id: str) -> list[Turn]:
    """해당 세션의 이전 대화 목록을 시간순으로 반환한다. 없으면 빈 리스트."""
    return _sessions.get(session_id, [])


def append_turn(session_id: str, question: str, sql: str, summary: str) -> None:
    """이번 턴(질문/SQL/요약)을 세션 히스토리 끝에 추가한다.

    _MAX_HISTORY_PER_SESSION을 넘으면 오래된 턴부터 잘라내서, 세션이
    오래 이어져도 메모리를 무한정 잡아먹지 않도록 한다.
    """
    history = _sessions.setdefault(session_id, [])
    history.append({"question": question, "sql": sql, "summary": summary})
    if len(history) > _MAX_HISTORY_PER_SESSION:
        del history[: len(history) - _MAX_HISTORY_PER_SESSION]
