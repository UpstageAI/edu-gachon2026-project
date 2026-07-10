"""쿼리 서비스 — 컨트롤러와 에이전트 그래프 사이의 서비스 레이어.

컨트롤러(api.routes)는 HTTP 만 담당하고, 실제 처리(그래프 실행 + DTO 매핑 + 스트리밍)는
이 서비스가 한다. 그래프 인스턴스의 수명도 여기서 관리한다.

레이어: controller(api) → **service(여기)** → graph(nodes) → tools → repositories → DB
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from app.graph.builder import NODE_NAMES, build_graph
from app.graph.state import initial_state
from app.schemas.query import QueryResponse, StreamEvent

logger = logging.getLogger(__name__)
_ERR_MSG = "요청 처리 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요."


class QueryService:
    def __init__(self) -> None:
        self._graph = build_graph()

    async def run(self, question: str) -> QueryResponse:
        """질의를 끝까지 처리해 응답 DTO 로 매핑한다.

        입력: question(str)
        출력: QueryResponse
        """
        try:
            state = await self._graph.ainvoke(initial_state(question))
        except Exception:  # noqa: BLE001 — 외부(LLM/DB) 실패를 API 계약(error)으로 변환. 상세는 로그로만.
            logger.exception("query 실패")
            return QueryResponse(error=_ERR_MSG)
        answer = state.get("answer", {})
        table = answer.get("table", {})
        return QueryResponse(
            summary=answer.get("summary", ""),
            columns=table.get("columns", []),
            rows=table.get("rows", []),
            sql=state.get("sql", ""),
            difficulty=state.get("difficulty", ""),
            model=state.get("model", ""),
            error=state.get("error", ""),
        )

    async def stream(self, question: str) -> AsyncIterator[StreamEvent]:
        """노드 완료 시점을 StreamEvent 로 순차 방출한다 (event: node → done).

        입력: question(str)
        출력: StreamEvent 비동기 제너레이터
        """
        # 그래프를 한 번만 실행하고, format 노드 출력에서 최종 answer 를 캡처한다
        # (재-invoke 하면 LLM/SQL 비용 2배 + 스트림과 done 답변 불일치 위험).
        answer: dict = {}
        try:
            async for event in self._graph.astream_events(initial_state(question), version="v2"):
                if event.get("event") == "on_chain_end" and event.get("name") in NODE_NAMES:
                    output = event.get("data", {}).get("output", {}) or {}
                    yield StreamEvent(
                        event="node",
                        node=event["name"],
                        data=json.dumps(output, ensure_ascii=False, default=str),
                    )
                    if "answer" in output:  # format 노드가 쓴 최종 answer
                        answer = output["answer"]
        except Exception:  # noqa: BLE001 — 상세는 로그로만, 클라이언트엔 일반 메시지
            logger.exception("stream 실패")
            yield StreamEvent(event="error", data=_ERR_MSG)
            return
        yield StreamEvent(
            event="done",
            data=json.dumps(answer, ensure_ascii=False, default=str),
        )


# 앱 전역 서비스 인스턴스 (그래프 1회 컴파일)
query_service = QueryService()
