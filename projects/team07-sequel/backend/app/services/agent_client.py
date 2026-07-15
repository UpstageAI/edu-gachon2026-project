"""백엔드 <-> AI agent 연동 지점.

실제 agent 응답에는 summary/columns/rows/sql/difficulty/model/error가 들어있지만,
우리는 sql과 summary만 쓴다. agent가 이미 실행한 columns/rows는 신뢰하지 않고
버린다 — 백엔드가 자체 guardrail로 재검증하고 자체 읽기 전용 DB 커넥션으로
다시 실행하는 defense-in-depth 설계를 그대로 유지하기 위함이다 (query.py 참고).

agent_client.py 하나만 교체하면 되도록 설계해뒀던 대로, main.py/query.py 등
나머지 코드는 이번에도 손대지 않았다.

`AgentResult`에서 `suggested_questions` 필드는 제거했다(애초에 `/query`
응답에 없는 필드였음). 추천 질문은 `fetch_suggestions()`가 별도로 반환한다.
"""

import httpx

from app.core.config import settings
from app.schemas.query import AgentResult


class AgentError(Exception):
    """AI agent가 자체적으로 처리 실패를 알려온 경우 (응답의 error 필드가 채워짐)."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def ask_ai_agent(question: str, session_id: str) -> AgentResult:
    """AI agent에 실제 HTTP로 SQL 생성을 요청한다.

    session_id는 agent가 자기 쪽 세션 히스토리(성공한 턴만 최근 5개)를
    찾는 키로 쓴다 — 백엔드가 히스토리 내용을 직접 구성해서 보내지 않는다.
    """
    async with httpx.AsyncClient(base_url=settings.AI_AGENT_BASE_URL, timeout=60) as client:
        resp = await client.post(
            "/api/v1/query",
            json={"question": question, "session_id": session_id},
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("error"):
        raise AgentError(data["error"])

    return AgentResult(sql=data.get("sql", ""), summary=data.get("summary", ""))


async def fetch_suggestions(session_id: str) -> list[str]:
    """방금 성공한 턴을 바탕으로 agent가 예측한 후속 질문(0~2개)을 가져온다.

    `/api/v1/query`가 성공적으로 끝난 "직후"에만 호출 의미가 있다 — agent는
    이 호출 시점에 자기 세션 히스토리에 저장된 직전 성공 턴을 읽어서 추천을
    만든다. 빈 배열은 정상(직전 턴이 없거나 실패했거나, agent가 적절한
    추천을 못 찾은 경우)이라 에러로 취급하지 않는다. 이 호출 자체가
    실패하더라도(네트워크 등) 추천 질문은 부가 기능이라 전체 응답을
    실패시키지 않고 빈 배열로 처리한다 — 호출부(query.py)에서 try/except로
    감싼다.
    """
    async with httpx.AsyncClient(base_url=settings.AI_AGENT_BASE_URL, timeout=30) as client:
        resp = await client.post("/api/v1/suggestions", json={"session_id": session_id})
        resp.raise_for_status()
        data = resp.json()

    return data.get("suggestions", [])
