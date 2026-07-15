"""Retry & Fallback 체인 테스트 (Day5 파트 B).

실제 Upstage·Langfuse를 호출하지 않는다 — _completion을 monkeypatch로 대체하고
model 인자 기록으로 호출 순서를 검증한다. LANGFUSE_ENABLED=false 전제로 동작하며,
Langfuse 정합성 테스트는 fake client를 직접 주입한다.
검색은 tests/conftest.py의 autouse fixture가 mock repository로 교체한다.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from litellm import exceptions as litellm_exceptions  # noqa: E402
from loguru import logger  # noqa: E402

from app.core import llm, observability  # noqa: E402
from app.core.llm import FALLBACK_MODEL, LLM_FAILURE_MESSAGE, LLMError, generate_text  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

MAIN = None  # _completion의 model 인자 미지정(None) = 메인 모델


def _retryable_error() -> Exception:
    return litellm_exceptions.InternalServerError(
        message="boom", llm_provider="openai", model="solar-pro3"
    )


class FakeCompletion:
    """_completion 대체 — 호출마다 model 인자를 기록하고 fail_times회까지 실패한다."""

    def __init__(self, fail_times: int = 0, error: Exception | None = None, mid_stream_fail: bool = False):
        self.calls: list = []
        self.fail_times = fail_times
        self.error = error or _retryable_error()
        self.mid_stream_fail = mid_stream_fail

    def __call__(self, messages, stream, model=None):
        self.calls.append(model)
        if len(self.calls) <= self.fail_times:
            raise self.error
        if stream:
            return self._stream_chunks()
        return {
            "choices": [{"message": {"content": "테스트 본문 답변"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }

    def _stream_chunks(self):
        yield {"choices": [{"delta": {"content": "첫 "}}]}
        if self.mid_stream_fail:
            raise _retryable_error()
        yield {"choices": [{"delta": {"content": "답변"}}]}


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(llm, "RETRY_WAIT_SECONDS", 0)


def _install(monkeypatch, fake: FakeCompletion) -> FakeCompletion:
    monkeypatch.setattr("app.core.llm._completion", fake)
    return fake


# 1. 메인 1회 실패 후 성공 → 정상 답변, 호출 2회 (전부 메인)
def test_main_retry_once_then_success(monkeypatch):
    fake = _install(monkeypatch, FakeCompletion(fail_times=1))

    response = client.post("/chat/sync", json={"message": "월세 계약 전에 뭘 확인해야 하나요?"})

    data = response.json()
    assert response.status_code == 200
    assert data["guardrail_blocked"] is False
    assert data["is_fallback"] is False
    assert "테스트 본문 답변" in data["answer"]
    assert fake.calls == [MAIN, MAIN]


# 2. 메인 2회 실패 → 대체 성공 → 정상 답변, 호출 순서 [메인, 메인, 대체] 정확히 3회
def test_fallback_model_succeeds_after_main_fails_twice(monkeypatch):
    fake = _install(monkeypatch, FakeCompletion(fail_times=2))

    response = client.post("/chat/sync", json={"message": "월세 계약 전에 뭘 확인해야 하나요?"})

    data = response.json()
    assert response.status_code == 200
    assert data["is_fallback"] is False
    assert "테스트 본문 답변" in data["answer"]
    assert fake.calls == [MAIN, MAIN, FALLBACK_MODEL]


# 3. 대체 성공 응답에 링크 문구·고지문 정상 부착
def test_fallback_model_answer_keeps_link_and_notice(monkeypatch):
    from app.agents.nodes import LEGAL_NOTICE

    fixed_url = "https://easylaw.go.kr/CSP/fixed"
    monkeypatch.setattr(
        "app.repositories.chroma_law_repository.get_source_url", lambda document_id: fixed_url
    )
    _install(monkeypatch, FakeCompletion(fail_times=2))

    response = client.post("/chat/sync", json={"message": "월세 계약 전에 뭘 확인해야 하나요?"})

    answer = response.json()["answer"]
    assert answer.index("테스트 본문 답변") < answer.index(fixed_url) < answer.index(LEGAL_NOTICE)


# 4. 전부 실패 → sync: is_fallback=true, 고정 문구, HTTP 200, 총 3회 (4회째 없음)
def test_all_attempts_fail_returns_fixed_message_with_200(monkeypatch):
    fake = _install(monkeypatch, FakeCompletion(fail_times=10))

    response = client.post("/chat/sync", json={"message": "월세 계약 전에 뭘 확인해야 하나요?"})

    data = response.json()
    assert response.status_code == 200
    assert data["is_fallback"] is True
    assert data["guardrail_blocked"] is False
    assert data["category"] == "기타"
    assert data["retrieved_count"] == 0
    assert data["answer"] == LLM_FAILURE_MESSAGE
    assert len(fake.calls) == 3  # 상한 보장 — 4회째 호출 없음


# 5. stream: 첫 토큰 전 전부 실패 → error 이벤트 (고정 문구 메시지)
def test_stream_all_attempts_fail_emits_error_event(monkeypatch):
    fake = _install(monkeypatch, FakeCompletion(fail_times=10))

    response = client.post("/chat/stream", json={"message": "월세 계약 전에 뭘 확인해야 하나요?"})

    assert response.status_code == 200
    assert "event: error" in response.text
    assert LLM_FAILURE_MESSAGE in response.text
    assert len(fake.calls) == 3


# 6. stream: 첫 토큰 전 메인 2회 실패 → 대체 모델로 스트리밍 성공
def test_stream_switches_to_fallback_model_before_first_token(monkeypatch):
    fake = _install(monkeypatch, FakeCompletion(fail_times=2))

    response = client.post("/chat/stream", json={"message": "월세 계약 전에 뭘 확인해야 하나요?"})

    assert response.status_code == 200
    assert "첫 " in response.text
    assert "답변" in response.text
    assert "event: done" in response.text
    assert fake.calls == [MAIN, MAIN, FALLBACK_MODEL]


# 7. stream: 토큰 일부 후 실패 → 추가 호출 없이 즉시 error
def test_stream_mid_failure_does_not_retry(monkeypatch):
    fake = _install(monkeypatch, FakeCompletion(fail_times=0, mid_stream_fail=True))

    response = client.post("/chat/stream", json={"message": "월세 계약 전에 뭘 확인해야 하나요?"})

    assert response.status_code == 200
    assert "event: error" in response.text
    assert len(fake.calls) == 1  # 재시도·전환 없음


# 8. 재시도·전환 warning 로그 기록
def test_retry_and_switch_warnings_are_logged(monkeypatch):
    _install(monkeypatch, FakeCompletion(fail_times=2))
    records: list[str] = []
    handler_id = logger.add(lambda message: records.append(str(message)), level="WARNING")
    try:
        client.post("/chat/sync", json={"message": "월세 계약 전에 뭘 확인해야 하나요?"})
    finally:
        logger.remove(handler_id)

    joined = "".join(records)
    assert "재시도" in joined
    assert "대체 모델로 전환" in joined
    assert "fallback model" in joined


# 9. 재시도 대상 아닌 예외(TypeError)는 즉시 전파 (재시도·전환 없음)
def test_non_retryable_exception_propagates_immediately(monkeypatch):
    fake = _install(monkeypatch, FakeCompletion(fail_times=10, error=TypeError("bug")))

    with pytest.raises(LLMError) as exc_info:
        generate_text("월세 계약 전에 뭘 확인해야 하나요?")

    assert isinstance(exc_info.value.__cause__, TypeError)
    assert len(fake.calls) == 1


# 10. (Langfuse 정합성) 대체 모델 응답 시 generation observation에
#     실제 사용 모델과 retry metadata가 기록된다
def test_generation_observation_records_actual_model_and_retry_metadata(monkeypatch):
    class FakeObservation:
        def __init__(self, record):
            self.record = record

        def update(self, **kwargs):
            self.record["updates"].append(kwargs)

    class FakeContext:
        def __init__(self, record):
            self.record = record

        def __enter__(self):
            return FakeObservation(self.record)

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakeLangfuseClient:
        def __init__(self):
            self.records = []

        def start_as_current_observation(self, **kwargs):
            record = {"kwargs": kwargs, "updates": []}
            self.records.append(record)
            return FakeContext(record)

        def flush(self):
            pass

    fake_langfuse = FakeLangfuseClient()
    monkeypatch.setattr(observability, "_get_langfuse_client", lambda: fake_langfuse)
    _install(monkeypatch, FakeCompletion(fail_times=2))

    client.post("/chat/sync", json={"message": "월세 계약 전에 뭘 확인해야 하나요?"})

    generation = next(
        record for record in fake_langfuse.records if record["kwargs"]["name"] == "generation"
    )
    merged_updates = {key: value for update in generation["updates"] for key, value in update.items()}
    assert merged_updates["model"] == FALLBACK_MODEL  # 실제 사용 모델 기록 (v4 정합성)
    assert merged_updates["metadata"]["retry_count"] == 2
    assert merged_updates["metadata"]["used_fallback_model"] is True
    assert merged_updates["output"]  # 최종 성공 output은 generation에 기록 (조건 5)
