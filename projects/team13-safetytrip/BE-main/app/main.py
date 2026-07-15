"""
FastAPI 앱. SSE로 parsed -> stats -> [escalate|citation+token 반복] -> done 순서로 흘려보냄.
(프론트 UI의 지역/시기/동반자 패널, 위험도 점수 차트, 인용 배지에 맞춘 이벤트 구조)

실행: uvicorn app.main:app --reload --port 8000
테스트: curl -N -X POST http://localhost:8000/chat/stream \
        -H "Content-Type: application/json" \
        -d '{"query": "8월 초에 부모님 모시고 부산 해운대 가는데 주의할 게 있을까?"}'
"""
import sys
import os
import json
import uuid

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.graph.build_graph import build_graph
from app.checkpointer import get_checkpointer
from app.llm_client import (
    build_respond_prompt,
    stream_response_safe,
    build_degraded_fallback_text,
    LLMUnavailableError,
    LLMStreamInterruptedError,
)
from app.citation import build_citation_ids
from preprocessors.disaster_type_phone_map import get_contact
from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

app = FastAPI(title="재난안전 여행 가이드 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 배포 시 실제 프론트엔드 도메인으로 제한
    allow_methods=["*"],
    allow_headers=["*"],
)

# 체크포인터 연결: thread_id 기준으로 대화 세션 상태가 Supabase에 저장/복원됨
# (테이블은 사전에 loaders/setup_checkpointer.py로 1회 생성해둬야 함)
_graph = build_graph(checkpointer=get_checkpointer())


class ChatRequest(BaseModel):
    query: str
    thread_id: str | None = None  # 대화 세션 ID. 프론트가 이전 응답에서 받은 값을
                                    # 그대로 다시 보내면 대화가 이어짐. 없으면 새로 생성.


def sse_event(event: str, data: dict) -> str:
    """SSE 포맷 한 줄 생성"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def compute_risk_scores(breakdown: list, top_n: int = 3) -> list:
    """
    프론트 '위험도 점수' 차트용 0~100 스케일 점수 계산.
    "기타"(재난유형 아닌 잡다한 안전공지)는 제외하고, 상위 top_n개 안에서의
    상대 비중으로 재계산함 (기타 비율에 가려서 실제 재난 위험도가 왜곡되는 걸 방지).
    """
    real_types = [b for b in breakdown if b["disaster_type"] != "기타"][:top_n]
    if not real_types:
        return []

    total = sum(b["count"] for b in real_types)
    if total == 0:
        return []

    return [
        {
            "disaster_type": b["disaster_type"],
            "risk_score": round(b["count"] / total * 100),
            "count": b["count"],
        }
        for b in real_types
    ]


def generate_sse_stream(user_query: str, thread_id: str):
    # 0) 세션 ID 안내 (제일 먼저, 어떤 분기로 가든 항상 전송)
    # 프론트는 이 값을 저장해두고, 다음 요청 body의 thread_id에 그대로 담아 보내면
    # 대화가 이어짐 (지역/시기/동반자 등 이전 턴 맥락을 이어받음)
    yield sse_event("session", {"thread_id": thread_id})

    # 1) 그래프 실행 (parse -> stats/retrieve -> gate, 여기까진 논스트리밍)
    # parse 단계에서 Solar API가 재시도까지 소진하고 완전히 실패하면 LLMUnavailableError 발생
    try:
        langfuse_handler = LangfuseCallbackHandler()
        result_state = _graph.invoke(
            {"user_query": user_query},
            config={
                "callbacks": [langfuse_handler],
                "configurable": {"thread_id": thread_id},
            },
        )
    except LLMUnavailableError:
        yield sse_event("error", {
            "message": "일시적으로 AI 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.",
            "contact": get_contact("기타"),
        })
        yield sse_event("done", {})
        return

    # 2) 파싱 실패 -> 재질문 요청
    # (reactive 질문은 region_sido/disaster_type 없어도 정상 진행 - 그래프의
    #  route_after_parse와 동일한 기준. disaster_type 없어도 원본 질문으로
    #  검색하는 폴백 경로가 retrieve_node에 있음)
    intent = result_state.get("intent")
    is_unrecoverable = (
        result_state.get("parse_failed")
        or (intent == "prevention" and not result_state.get("region_sido"))
        or intent not in ("prevention", "reactive")
    )
    if is_unrecoverable:
        yield sse_event("reask", {
            "message": "지역과 시기를 조금 더 구체적으로 말씀해 주시겠어요? "
                       "예: '8월 초에 부산 해운대 여행 가는데 주의할 점이 있을까요?'"
        })
        yield sse_event("done", {})
        return

    # 3) parsed 이벤트: 지역/시기/동반자 (프론트 좌측 패널용)
    region_sido = result_state.get("region_sido")
    region_sigungu = result_state.get("region_sigungu")
    region_label = " ".join(p for p in [region_sido, region_sigungu] if p) or "-"
    month = result_state.get("month")
    month_label = f"{month}월" if month else "-"
    companions_label = "노약자 동반" if result_state.get("has_vulnerable") else "-"

    yield sse_event("parsed", {
        "region": region_label,
        "month": month_label,
        "companions": companions_label,
        "intent": intent,
        "disaster_type": result_state.get("disaster_type"),
    })

    # 4) stats 이벤트: 위험도 점수 차트용 데이터
    stats_result = result_state.get("stats_result")
    if stats_result:
        risk_scores = compute_risk_scores(stats_result.breakdown)
        yield sse_event("stats", {
            "scope_used": stats_result.scope_used,
            "total_count": stats_result.total_count,
            "risk_scores": risk_scores,
            "top_risk": risk_scores[0]["disaster_type"] if risk_scores else None,
            "fallback_notice": stats_result.fallback_notice,
        })

    # 5) 에스컬레이션 분기
    if result_state.get("should_escalate"):
        from app.graph.nodes import escalate_node
        escalate_result = escalate_node(result_state)
        contact = escalate_result["escalate_contact"]
        yield sse_event("escalate", {
            "reason": result_state.get("escalate_reason"),
            "contact": contact,
            "message": (
                f"공식 매뉴얼에서 충분한 근거를 찾지 못했습니다. "
                f"아래 기관으로 문의해 주세요: {contact['agency']} ({contact['phone']})"
            ),
        })
        yield sse_event("done", {})
        return

    # 6) citation 이벤트: 인용 배지 (GUIDE-HEAT-ELDERLY-001 형식)
    retrieved_guidelines = result_state.get("retrieved_guidelines") or []
    citation_ids = build_citation_ids(retrieved_guidelines)
    yield sse_event("citation", {"ids": citation_ids})

    # 7) 정상 응답: LLM 스트리밍 (3단 방어 적용됨 - stream_response_safe 내부에서
    #    timeout/재시도 처리하고, 그래도 실패하면 예외로 알려줌)
    messages = build_respond_prompt(
        user_query=user_query,
        stats_result=stats_result,
        retrieved_guidelines=retrieved_guidelines,
        has_vulnerable=result_state.get("has_vulnerable", False),
    )

    try:
        for token in stream_response_safe(messages):
            yield sse_event("token", {"text": token})

    except LLMUnavailableError:
        # ③ 최종 실패, 토큰 하나도 못 보낸 상태 -> 행동요령 원문 + 대응기관 안내로 강등
        fallback_text = build_degraded_fallback_text(retrieved_guidelines)
        yield sse_event("degraded", {
            "reason": "AI 응답 생성 서비스에 일시적 장애가 발생했습니다.",
            "contact": get_contact(result_state.get("disaster_type") or "기타"),
        })
        yield sse_event("token", {"text": fallback_text})

    except LLMStreamInterruptedError:
        # ③ 부분 실패, 이미 일부 답변은 전송됨 -> 이어서 중단 안내만 추가 (재시작하면 중복되므로 안 함)
        contact = get_contact(result_state.get("disaster_type") or "기타")
        yield sse_event("token", {
            "text": f"\n\n(※ 응답 생성이 중간에 중단되었습니다. 추가 문의는 {contact['agency']} "
                    f"({contact['phone']})로 연락해 주세요.)"
        })

    yield sse_event("done", {})


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    thread_id = req.thread_id or str(uuid.uuid4())
    return StreamingResponse(
        generate_sse_stream(req.query, thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx 등에서 SSE 버퍼링 방지
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}