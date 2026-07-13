"""백엔드 <-> AI agent 연동 지점.

2026-07-10 업데이트: 팀원의 aiagent 브랜치가 main에 병합되고, 실제 Cloud Run
서비스(text2sql-agent)로 배포된 것을 확인해서 mock을 실제 HTTP 호출로 교체했다.
(이전에 한 번 "실제 스펙"으로 보고 연동했다가, 그게 강사 측 벤치마킹용 예시
코드였음이 드러나 mock으로 롤백한 적이 있다 — 이번엔 실제 코드(app/main.py,
app/api/routes.py, app/schemas/query.py)를 직접 확인하고 진행한 것이라 다르다.)

실제 agent 응답에는 summary/columns/rows/sql/difficulty/model/error가 들어있지만,
우리는 sql과 summary만 쓴다. agent가 이미 실행한 columns/rows는 신뢰하지 않고
버린다 — 백엔드가 자체 guardrail로 재검증하고 자체 읽기 전용 DB 커넥션으로
다시 실행하는 defense-in-depth 설계를 그대로 유지하기 위함이다 (query.py 참고).

agent_client.py 하나만 교체하면 되도록 설계해뒀던 대로, main.py/query.py 등
나머지 코드는 이번에도 손대지 않았다.

2026-07-13 업데이트: `docs/api.md`(권도윤 님 병합 완료 버전)를 직접 확인하고
실제 계약에 맞게 아래 두 가지를 고쳤다 — 처음에 placeholder로 가정했던
형태와 실제 계약이 달랐다.

  1. `history`를 배열로 만들어서 매번 보내는 게 아니라, agent가 `session_id`
     기준으로 **자기 자신의 히스토리를 서버 안에서 직접 관리**한다(성공한 턴만
     최근 5개, 세션 30분 idle 시 만료). 그래서 백엔드는 history를 구성할 필요
     없이 `session_id`만 그대로 실어 보내면 된다.
  2. 추천 후속 질문은 `/api/v1/query` 응답에 같이 오는 게 아니라, 완전히
     별도의 `POST /api/v1/suggestions` 엔드포인트({"session_id"} ->
     {"suggestions": [...]}, 0~2개)를 답변을 받은 "직후" 별도로 호출해야
     한다. agent가 방금 성공한 턴을 자기 히스토리에서 읽어 추천을 만들기
     때문에, 이 호출도 `/api/v1/query`와 같은 session_id로 해야 한다.

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
