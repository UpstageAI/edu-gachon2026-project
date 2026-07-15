"""LangGraph 에이전트 상태 정의."""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

    # Router가 결정한 의도. ask_year = 학번(입학년도)을 한 번 되묻는 흐름.
    # out_of_scope = 인공지능학과(구 AI·소프트웨어학부) 외 학과 질문 → 전용 챗봇 안내.
    intent: Literal["chat", "rag", "tool", "reminder", "ask_year", "out_of_scope"] | None

    # 이번 턴에 실제로 처리할 질문 텍스트. 보통 messages[-1]이지만, 학번 되묻기 뒤
    # 사용자가 학번만 답한 턴에서는 '원래 질문'(pending.orig_query)으로 복원된다.
    query: str | None

    # 사용자 학번(입학년도, 예: 2023). 세션 내내 체크포인터로 유지된다.
    # 졸업요건·교육과정처럼 학번에 따라 답이 갈리는 질문에서 검색 년도 필터에 쓴다.
    admission_year: int | None

    # 학번을 이미 한 번 물어봤는지. True면(사용자가 답을 안 줬어도) 다시 나그하지 않는다.
    year_prompted: bool

    # 이번 rag 검색에 실제 적용한 교육과정 년도(admission_year를 보유 데이터로 매핑한 값).
    # 응답 그라운딩에서 "어느 년도 기준으로 안내했는지" 투명하게 밝히는 데 쓴다.
    applied_curriculum_year: int | None

    # Router가 분류한 카테고리 후보들 (rag 검색 필터용). None이면 전체 검색.
    # 하나의 category로 확정하지 않고, 관련 있을 수 있는 category_l1을 모두 담는다.
    category_l1: list[str] | None

    # RAG 검색 결과 (문서 내용 + 출처)
    retrieved_docs: list[dict]

    # Tool 정보
    tool_name: str | None
    tool_args: dict | None
    tool_result: dict | None

    # 가드레일: RAG로 답을 못 찾아 문의처로 안내해야 할 때
    guardrail: bool
    contact: dict | None

    # 순수 연락처 질문(예: "학과사무실 전화번호")인지. True면 응답에서 "자료에서
    # 확인 어렵다" 얼버무림 없이 contacts.json의 번호를 자신 있게 바로 안내한다.
    is_contact_question: bool

    session_id: str

    # 리마인드 등 여러 턴에 걸친 사용자 확인 절차 진행 상태.
    # {"type": "reminder", "stage": "confirm" | "awaiting_email", "content": str} | None
    # 체크포인터로 턴 간 영속되며, 확인 절차가 없을 때는 None.
    pending_action: dict | None


def create_initial_state(session_id: str, messages: list[BaseMessage] | None = None) -> AgentState:
    return AgentState(
        messages=messages or [],
        intent=None,
        query=None,
        admission_year=None,
        year_prompted=False,
        applied_curriculum_year=None,
        category_l1=None,
        retrieved_docs=[],
        tool_name=None,
        tool_args=None,
        tool_result=None,
        guardrail=False,
        contact=None,
        is_contact_question=False,
        session_id=session_id,
        pending_action=None,
    )
