"""쿼리 서비스 — 컨트롤러와 에이전트 그래프 사이의 서비스 레이어.

컨트롤러(api.routes)는 HTTP 만 담당하고, 실제 처리(그래프 실행 + DTO 매핑 + 스트리밍)는
이 서비스가 한다. 그래프 인스턴스의 수명도 여기서 관리한다.

레이어: controller(api) → **service(여기)** → graph(nodes) → tools → repositories → DB
"""
from __future__ import annotations

import json
import logging
import time
from typing import AsyncIterator

from app.core import prompts
from app.core.llm import collect_usage, complete
from app.core.observability import graph_callbacks
from app.core.pricing import token_cost_usd
from app.core.session_store import session_store
from app.graph.builder import NODE_NAMES, build_graph
from app.graph.state import initial_state
from app.schemas.query import QueryResponse, StreamEvent

logger = logging.getLogger(__name__)
_ERR_MSG = "요청 처리 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요."


class QueryService:
    def __init__(self) -> None:
        self._graph = build_graph()

    async def run(self, question: str, session_id: str | None = None) -> QueryResponse:
        """질의를 끝까지 처리해 응답 DTO 로 매핑한다.

        입력: question(str), session_id(옵션 — 있으면 이전 턴 반영 + 성공 시 턴 기록)
        출력: QueryResponse
        """
        history = session_store.get_history(session_id)
        with collect_usage() as usage:  # 이 질의의 전 노드 LLM 토큰 합산
            t0 = time.perf_counter()
            try:
                state = await self._graph.ainvoke(
                    initial_state(question, history), config={"callbacks": graph_callbacks()})
            except Exception:  # noqa: BLE001 — 외부(LLM/DB) 실패를 API 계약(error)으로 변환. 상세는 로그로만.
                logger.exception("query 실패")
                return QueryResponse(error=_ERR_MSG, latency_ms=int((time.perf_counter() - t0) * 1000))
            latency_ms = int((time.perf_counter() - t0) * 1000)
        answer = state.get("answer", {})
        table = answer.get("table", {})
        rows = table.get("rows", [])
        if rows:  # 실패/무결과 턴은 다음 턴 맥락·후속질문 재료로 남기지 않는다
            session_store.append_turn(session_id, question, state.get("sql", ""), answer.get("summary", ""))
        return QueryResponse(
            summary=answer.get("summary", ""),
            columns=table.get("columns", []),
            rows=rows,
            sql=state.get("sql", ""),
            difficulty=state.get("difficulty", ""),
            model=state.get("model", ""),
            error=state.get("error", ""),
            latency_ms=latency_ms,
            total_tokens=usage["input"] + usage["output"],
            cost_usd=token_cost_usd(usage["input"], usage["output"]),
        )

    async def stream(self, question: str, session_id: str | None = None) -> AsyncIterator[StreamEvent]:
        """노드 완료 시점을 StreamEvent 로 순차 방출한다 (event: node → done).

        입력: question(str), session_id(옵션 — 있으면 이전 턴 반영 + 성공 시 턴 기록)
        출력: StreamEvent 비동기 제너레이터
        """
        history = session_store.get_history(session_id)
        # 그래프를 한 번만 실행하고, format 노드 출력에서 최종 answer 를 캡처한다
        # (재-invoke 하면 LLM/SQL 비용 2배 + 스트림과 done 답변 불일치 위험).
        answer: dict = {}
        with collect_usage() as usage:  # 이 질의의 전 노드 LLM 토큰 합산
            t0 = time.perf_counter()
            try:
                async for event in self._graph.astream_events(
                        initial_state(question, history), version="v2", config={"callbacks": graph_callbacks()}):
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
            latency_ms = int((time.perf_counter() - t0) * 1000)
        if answer.get("table", {}).get("rows"):  # 실패/무결과 턴은 히스토리에 남기지 않는다
            session_store.append_turn(session_id, question, answer.get("sql", ""), answer.get("summary", ""))
        # done 페이로드에 관측 메타를 얹는다(동기 /query 의 latency_ms/total_tokens/cost_usd 와 동일 값).
        answer = {**answer, "meta": {
            "latency_ms": latency_ms,
            "total_tokens": usage["input"] + usage["output"],
            "cost_usd": token_cost_usd(usage["input"], usage["output"]),
        }}
        yield StreamEvent(
            event="done",
            data=json.dumps(answer, ensure_ascii=False, default=str),
        )

    async def suggest_followups(self, session_id: str) -> list[str]:
        """직전 성공 턴을 바탕으로 후속질문을 최대 2개 제안한다.

        입력: session_id(필수)
        출력: list[str] (0~2개; 히스토리 없음/만료는 빈 리스트 — 정상 케이스)
        """
        history = session_store.get_history(session_id)
        if not history:
            return []
        last = history[-1]
        ctx = f"질문: {last['q']}\nSQL: {last['sql']}\n요약: {last['result_summary']}"
        try:
            res = complete("solar-mini", [
                {"role": "system", "content": prompts.FOLLOWUP},
                {"role": "user", "content": ctx},
            ], temperature=0.3)
        except Exception:  # noqa: BLE001 — run()/stream() 과 동일: 외부 호출 실패는 빈 결과로 흡수
            logger.exception("suggest_followups 실패")
            return []
        try:
            obj = json.loads(res.text)
        except (json.JSONDecodeError, TypeError):
            obj = None
        if not isinstance(obj, dict):  # LLM 이 계약을 어겨도 안전 기본값(빈 리스트)
            return []
        suggestions = obj.get("suggestions")
        if not isinstance(suggestions, list):
            return []
        return [s for s in suggestions if isinstance(s, str) and s.strip()][:2]


# 앱 전역 서비스 인스턴스 (그래프 1회 컴파일)
query_service = QueryService()
