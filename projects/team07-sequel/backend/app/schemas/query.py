from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """프론트엔드 -> 백엔드 요청 스펙."""

    question: str = Field(..., min_length=1, description="사용자의 자연어 질문")
    session_id: str = Field(..., description="대화 세션 식별자 (프론트에서 생성/유지)")


class AgentResult(BaseModel):
    """백엔드 -> AI agent 호출 결과 (agent_client.py의 반환 타입).

    실제 AI agent의 응답 형태가 무엇이든, agent_client.py 안에서 이 형태로
    변환해서 반환하면 나머지 코드는 전혀 바뀌지 않는다.
    """

    sql: str
    summary: str
    # 2026-07-13: 추천 후속 질문은 이 응답(/api/v1/query)에 포함되지 않는다.
    # 별도의 /api/v1/suggestions 호출로 받아오므로(agent_client.fetch_suggestions
    # 참고) 여기엔 필드를 두지 않는다.


class SSEEvent:
    """SSE 이벤트 타입 이름 상수."""

    STATUS = "status"
    RESULT = "result"
    SQL = "sql"
    DONE = "done"
    ERROR = "error"


class ErrorCode:
    """에러 이벤트의 code 필드에 들어갈 값. 프론트엔드는 이 값으로 안내 문구를 분기."""

    VALIDATION_FAILED = "VALIDATION_FAILED"       # 안전하지 않은 쿼리로 판단되어 차단됨
    NO_RESULT = "NO_RESULT"                       # 조건에 맞는 결과 없음
    AMBIGUOUS_QUESTION = "AMBIGUOUS_QUESTION"      # 질문이 모호해서 SQL 생성 불가
    RESULT_VALIDATION_FAILED = "RESULT_VALIDATION_FAILED"  # 실행 결과의 스키마/타입이 비정상
    INTERNAL_ERROR = "INTERNAL_ERROR"              # 그 외 서버 내부 오류
