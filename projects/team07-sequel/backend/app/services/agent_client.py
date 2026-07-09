"""백엔드 <-> AI agent 연동 지점.

현재 결정된 것: AI agent는 별도 서비스로 분리해서 HTTP로 호출할 예정이지만,
요청/응답 스펙, 에러 처리 규약, 세션·트레이싱 ID 공유 방식은 아직 팀원과
미정 상태다. (한 번 실제 스펙으로 보이는 문서를 보고 연동했었으나, 그건
강사 측이 제공한 벤치마킹용 가이드 코드였고 teammate의 실제 스펙은 아직
확정되지 않았음이 확인되어 mock으로 되돌림 — 2026-07-09)

그 사이 프론트엔드/백엔드 통합 개발이 막히지 않도록, 이 함수 하나로
AI agent 호출 지점을 감싸두고 지금은 목업(mock) 응답을 반환한다.
나중에 실제 스펙이 확정되면 이 함수 내부만 실제 HTTP 호출로 교체하면
되고, main.py/query.py 등 나머지 코드는 손댈 필요가 없다.
"""

from app.core.config import settings
from app.schemas.query import AgentResult

# 실제 연동 시 사용할 예시 (미정 스펙이 확정되면 주석 해제 후 구현)
# import httpx
#
# async def ask_ai_agent(question: str, history: list[dict]) -> AgentResult:
#     async with httpx.AsyncClient(base_url=settings.AI_AGENT_BASE_URL, timeout=30) as client:
#         resp = await client.post("/agent/query", json={"question": question, "history": history})
#         resp.raise_for_status()
#         data = resp.json()
#         return AgentResult(sql=data["sql"], summary=data["summary"])


async def ask_ai_agent(question: str, history: list[dict]) -> AgentResult:
    """TODO: AI agent 실제 HTTP 호출로 교체 예정. 지금은 통합 테스트용 목업 응답."""

    return AgentResult(
        sql=(
            "SELECT p.product_category_name, COUNT(*) AS order_count "
            "FROM olist_order_items oi "
            "JOIN olist_products p ON oi.product_id = p.product_id "
            "GROUP BY p.product_category_name "
            "ORDER BY order_count DESC "
            "LIMIT 10;"
        ),
        summary=(
            "(임시 목업 응답) 이 문장은 AI agent 연동 전까지 고정으로 반환됩니다. "
            f"질문: '{question}' / 세션에 쌓인 이전 대화: {len(history)}건"
        ),
    )
