"""main.py (FastAPI 컨트롤러) 단위 테스트.

실제 Solar API를 타지 않도록 get_agent 의존성을 MockLLM 기반 에이전트로
오버라이드한다 (main.py의 기본 _agent는 SolarLLM을 쓰므로 그대로 두면 테스트가
네트워크·키에 의존하게 된다).
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

import main
from app.agent.loop import RecommendationAgent
from app.agent.mock_llm import MockLLM

main.app.dependency_overrides[main.get_agent] = lambda: RecommendationAgent(llm=MockLLM())
client = TestClient(main.app)


def _parse_sse(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def test_health_returns_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_recommend_streams_sse_content_type():
    resp = client.get("/recommend", params={"text": "안전하고 조용한 동네가 좋아요"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")


def test_recommend_recommendation_events_shape():
    resp = client.get("/recommend", params={"text": "안전하고 조용한 동네가 좋아요"})
    events = _parse_sse(resp.text)

    assert events[0]["type"] == "meta"
    assert events[0]["kind"] == "recommendation"
    assert set(events[0]["data"].keys()) == {"weights", "recommendations"}
    assert events[-1] == {"type": "done"}
    assert all(e["type"] == "delta" for e in events[1:-1])
    assert len(events) > 2  # meta + 여러 delta + done


def test_recommend_clarify_events_shape():
    resp = client.get("/recommend", params={"text": "아무데나 좋은 곳"})
    events = _parse_sse(resp.text)

    types_ = [e["type"] for e in events]
    assert types_ == ["meta", "delta", "done"]
    assert events[0]["kind"] == "clarify"


# ---------- top_n: 지도 등 대량 소비자를 위해 API에도 열려 있어야 함 ----------
# (streamlit_app.py는 지도용으로 top_n=500을 쓰는데, 예전엔 API가 3으로
#  고정돼 있어서 같은 기능을 API로는 절대 못 받았다 — 그 간극을 메운 부분.)

def test_recommend_top_n_defaults_to_three():
    resp = client.get("/recommend", params={"text": "안전하고 조용한 동네가 좋아요"})
    events = _parse_sse(resp.text)
    assert len(events[0]["data"]["recommendations"]) == 3


def test_recommend_top_n_query_param_overrides_default():
    resp = client.get("/recommend", params={"text": "안전하고 조용한 동네가 좋아요", "top_n": 10})
    events = _parse_sse(resp.text)
    assert len(events[0]["data"]["recommendations"]) == 10


def test_recommend_explain_stays_based_on_top_three_regardless_of_top_n():
    """data.recommendations는 top_n개를 다 담아도, 근거 설명(delta 전체)은 항상
    상위 3개만 근거로 삼아야 한다 — 안 그러면 top_n=500일 때 프롬프트에 500개
    동네 수치를 통째로 실어보내게 된다(MockLLM은 비용은 없지만 개수는 그대로 드러남)."""
    resp = client.get("/recommend", params={"text": "안전하고 조용한 동네가 좋아요", "top_n": 50})
    events = _parse_sse(resp.text)
    assert len(events[0]["data"]["recommendations"]) == 50
    full_message = "".join(e["text"] for e in events if e["type"] == "delta")
    assert full_message.count("**") == 6  # MockLLM.explain은 추천지마다 "**{구} {동}**" 제목 한 번(별표 2개)


# ---------- /health: mock 여부 노출 (main.py도 streamlit_app.py와 같은 판단 공유) ----------

def test_health_reports_mock_llm_true_without_key(monkeypatch):
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    resp = client.get("/health")
    assert resp.json() == {"status": "ok", "mock_llm": True}
