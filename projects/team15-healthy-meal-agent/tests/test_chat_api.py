"""
tests/test_chat_api.py
/api/v1/chat, /api/v1/chat/sync 엔드포인트 테스트.
LLM은 네트워크에 의존하므로 조건추출을 stub으로 monkeypatch해 결정적으로 돌린다.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.services.condition_extractor import extract_conditions_stub
from app.services.intent_router import classify_intent_stub
from backend import main
from backend.main import app


@pytest.fixture
def client(monkeypatch):
    # 실제 Solar 호출 대신 stub 사용 (네트워크·API키 불필요)
    # 의도분류·조건추출 둘 다 규칙기반 stub으로 고정
    monkeypatch.setattr(main.chat, "extract_conditions_llm", extract_conditions_stub)
    monkeypatch.setattr(main.chat, "classify_intent_llm", classify_intent_stub)
    return TestClient(app)


def test_chat_sync_returns_recommendation(client):
    """동기 엔드포인트가 추천 식단과 검증 결과를 돌려주는지."""
    resp = client.post(
        "/api/v1/chat/sync",
        json={"message": "400kcal 이하로, 계란은 빼고 야채 많은 한 끼 추천해줘"},
    )
    assert resp.status_code == 200
    body = resp.json()

    # 최종 응답 텍스트가 채워졌는지
    assert body["final_response"] != ""
    # 검증 등급이 유효한 값인지
    assert body["status"] in ("PASS", "PASS_WITH_WARNING", "FAIL")
    # 추천이 성공했다면 음식 목록과 영양성분이 있어야 한다
    if body["status"] != "FAIL":
        assert len(body["items"]) > 0
        assert body["nutrition"] is not None


def test_chat_sync_rejects_empty_message(client):
    """빈 메시지는 422로 거부 (min_length=1)."""
    resp = client.post("/api/v1/chat/sync", json={"message": ""})
    assert resp.status_code == 422


def test_chat_stream_emits_result_event(client):
    """SSE 스트림이 result 이벤트로 최종 결과를 흘려보내는지."""
    with client.stream(
        "POST",
        "/api/v1/chat",
        json={"message": "400kcal 이하로 야채 많은 한 끼 추천해줘"},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        text = "".join(resp.iter_text())

    # start 상태 이벤트와 result 이벤트가 모두 존재해야 한다
    assert "event: status" in text
    assert "event: result" in text

    # result 이벤트의 data(JSON)에 final_response가 담겨 있는지 확인
    result_data = None
    for block in text.split("\n\n"):
        if "event: result" in block:
            for line in block.splitlines():
                if line.startswith("data: "):
                    result_data = json.loads(line[len("data: ") :])
    assert result_data is not None
    assert "final_response" in result_data


def test_chat_stream_handles_llm_failure(monkeypatch):
    """조건추출이 예외를 던지면 error 이벤트로 안전하게 닫히는지 (실패 케이스 처리)."""

    def boom(_msg):
        raise RuntimeError("LLM timeout")

    # 추천 경로(meal_recommend)로 확실히 들어가도록 분류기를 고정한 뒤,
    # 그 다음 단계인 조건추출에서 예외를 유발한다.
    monkeypatch.setattr(main.chat, "classify_intent_llm", lambda _msg: "meal_recommend")
    monkeypatch.setattr(main.chat, "extract_conditions_llm", boom)
    client = TestClient(app)

    with client.stream(
        "POST", "/api/v1/chat", json={"message": "400kcal 이하 한 끼 추천해줘"}
    ) as resp:
        assert resp.status_code == 200
        text = "".join(resp.iter_text())

    assert "event: error" in text
