"""원문 링크 부착 테스트 (파트 B 대행 작업).

실제 Upstage API·ChromaDB를 호출하지 않는다 — get_source_url을 monkeypatch로 대체.
검색은 tests/conftest.py의 autouse fixture가 mock repository로 교체한다.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.agents.nodes import (  # noqa: E402
    LEGAL_NOTICE,
    fallback_response,
    guardrail_exit,
    output_guardrail,
)
from app.main import app  # noqa: E402
from app.schemas.document import RetrievedDocument  # noqa: E402

client = TestClient(app)

FIXED_URL = "https://easylaw.go.kr/CSP/fixed-test-url"
LINK_LINE = f"더 도움이 필요하시면 {FIXED_URL} 에서 추가 정보를 확인할 수 있습니다."
GET_SOURCE_URL_PATH = "app.repositories.chroma_law_repository.get_source_url"


def _normal_state() -> dict:
    document = RetrievedDocument(
        id="law_2482", question="질문", answer="답변", category="부동산/임대차"
    )
    return {
        "message": "질문",
        "answer": "본문 답변입니다.",
        "documents": [document],
        "category": "부동산/임대차",
        "guardrail_blocked": False,
        "is_fallback": False,
        "retrieved_count": 1,
    }


def test_normal_answer_has_body_link_notice_in_order(monkeypatch):
    monkeypatch.setattr(GET_SOURCE_URL_PATH, lambda document_id: FIXED_URL)

    answer = output_guardrail(_normal_state())["answer"]

    assert answer.index("본문 답변입니다.") < answer.index(LINK_LINE) < answer.index(LEGAL_NOTICE)


def test_no_url_means_no_link_but_notice_remains(monkeypatch):
    monkeypatch.setattr(GET_SOURCE_URL_PATH, lambda document_id: None)

    answer = output_guardrail(_normal_state())["answer"]

    assert "더 도움이 필요하시면" not in answer
    assert LEGAL_NOTICE in answer


def test_get_source_url_error_does_not_break_answer(monkeypatch):
    def raise_runtime_error(document_id):
        raise RuntimeError("chroma_db/가 없습니다.")

    monkeypatch.setattr(GET_SOURCE_URL_PATH, raise_runtime_error)

    answer = output_guardrail(_normal_state())["answer"]  # 예외가 전파되면 테스트 실패

    assert "더 도움이 필요하시면" not in answer
    assert "본문 답변입니다." in answer
    assert LEGAL_NOTICE in answer


def test_blocked_and_fallback_answers_have_no_link(monkeypatch):
    monkeypatch.setattr(GET_SOURCE_URL_PATH, lambda document_id: FIXED_URL)

    blocked = output_guardrail(guardrail_exit({"message": "소장 좀 써주세요"}))
    fallback = output_guardrail(fallback_response({"message": "질문"}))

    assert "더 도움이 필요하시면" not in blocked["answer"]
    assert "더 도움이 필요하시면" not in fallback["answer"]


def test_stream_sends_link_and_notice_before_done(monkeypatch):
    monkeypatch.setattr(GET_SOURCE_URL_PATH, lambda document_id: FIXED_URL)

    def fake_stream_text(prompt: str, system=None):
        yield "본문 "
        yield "답변"

    monkeypatch.setattr("app.api.chat.stream_text", fake_stream_text)

    response = client.post(
        "/chat/stream",
        json={"message": "월세 계약 전에 뭘 확인해야 하나요?"},
    )

    text = response.text
    assert response.status_code == 200
    # 본문 token → (링크 → 고지문) token → done 순서
    assert text.index("본문 ") < text.index(FIXED_URL) < text.index(LEGAL_NOTICE)
    assert text.index(LEGAL_NOTICE) < text.index("event: done")
    assert "event: done\ndata: {}" in text
