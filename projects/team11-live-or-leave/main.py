"""
FastAPI 컨트롤러 — HTTP 요청을 받아 RecommendationAgent를 호출하고,
근거 설명을 SSE(Server-Sent Events)로 토큰 단위 스트리밍한다.

레이어 원칙: 이 파일은 HTTP 전송(라우팅·SSE 포맷팅)만 담당한다. 추천 로직·LLM
선택·에러 판단은 전부 app/agent/loop.py의 RecommendationAgent가 갖고 있다.

실행: uvicorn main:app --reload
"""
from __future__ import annotations

import json

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.agent.factory import get_recommendation_agent, using_mock_llm
from app.agent.loop import RecommendationAgent

app = FastAPI(title="살래말래 (Live or Leave)")

# MVP 단계라 전체 허용. 실제 배포 전에는 프론트 도메인으로 좁힐 것.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_agent() -> RecommendationAgent:
    # app.agent.factory의 프로세스 지연 싱글턴 — streamlit_app.py와 mock 폴백
    # 판단을 공유한다 (UPSTAGE_API_KEY 없으면 여기도 자동으로 MockLLM으로 낮춘다).
    return get_recommendation_agent()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mock_llm": using_mock_llm()}


@app.get("/recommend")
def recommend(
    text: str, top_n: int = 3, agent: RecommendationAgent = Depends(get_agent)
) -> StreamingResponse:
    """top_n 기본값 3(자연어 답변용). 지도처럼 전체 스코어링이 필요한 소비자는
    top_n=500까지 늘릴 수 있다 — 단 근거 설명은 top_n과 무관하게 항상 상위
    3개만 생성된다(agent.stream 참고)."""
    def event_stream():
        for event in agent.stream(text, top_n=top_n):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
