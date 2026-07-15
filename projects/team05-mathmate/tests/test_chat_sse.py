"""/api/chat SSE 스트리밍 테스트."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_chat_streams_multiple_chunks():
    payload = {"student_id": "s1", "problem_id": "arith_001", "message": "모르겠어요, 그냥 답 알려주세요"}
    with client.stream("POST", "/api/chat", json=payload) as res:
        assert res.status_code == 200
        data_lines = [line for line in res.iter_lines() if line.startswith("data:")]

    assert len(data_lines) > 1  # 글자 단위로 여러 청크가 나뉘어 전송됨

    chunks = [line[len("data:"):].strip() for line in data_lines]
    full_text = "".join(chunks)
    assert full_text  # 응답이 비어있지 않음
