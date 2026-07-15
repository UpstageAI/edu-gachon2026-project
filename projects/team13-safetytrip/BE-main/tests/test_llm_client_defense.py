"""
app/llm_client.py의 3단 방어 로직 유닛테스트.
실제 Solar API를 호출하지 않고, _stream_once/API 호출부를 목(mock)으로 대체해서
재시도/강등 분기가 의도대로 동작하는지 검증.
"""
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import pytest
import app.llm_client as llm_client


class FakeTransientError(Exception):
    """RETRYABLE_EXCEPTIONS를 대신할 테스트용 예외 (openai SDK 예외 생성자 의존 피함)"""
    pass


class FakeFatalError(Exception):
    """FATAL_EXCEPTIONS(인증/권한 오류)를 대신할 테스트용 예외"""
    pass


@pytest.fixture(autouse=True)
def patch_retryable(monkeypatch):
    monkeypatch.setattr(llm_client, "RETRYABLE_EXCEPTIONS", (FakeTransientError,))
    monkeypatch.setattr(llm_client, "FATAL_EXCEPTIONS", (FakeFatalError,))
    monkeypatch.setattr(llm_client.time, "sleep", lambda *_: None)  # 테스트 속도용


class TestCallWithBackoff:
    def test_success_first_try(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            return "ok"

        assert llm_client._call_with_backoff(fn) == "ok"
        assert calls["n"] == 1

    def test_retry_then_success(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] < 2:
                raise FakeTransientError("일시 오류")
            return "ok"

        assert llm_client._call_with_backoff(fn) == "ok"
        assert calls["n"] == 2  # 1번 실패 + 1번 성공

    def test_exhausts_retries_raises_original_exception(self):
        def fn():
            raise FakeTransientError("계속 실패")

        with pytest.raises(FakeTransientError):
            llm_client._call_with_backoff(fn)

    def test_non_retryable_exception_propagates_immediately(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise ValueError("재시도 대상 아님")

        with pytest.raises(ValueError):
            llm_client._call_with_backoff(fn)
        assert calls["n"] == 1  # 재시도 없이 즉시 전파돼야 함

    def test_fatal_exception_skips_retry_entirely(self):
        """인증/권한 오류는 RETRYABLE이 아니라 FATAL -> 재시도 없이 즉시 전파"""
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise FakeFatalError("인증 실패")

        with pytest.raises(FakeFatalError):
            llm_client._call_with_backoff(fn)
        assert calls["n"] == 1  # 재시도가 전혀 일어나지 않아야 함


class TestStreamResponseSafe:
    def test_success_no_retry_needed(self, monkeypatch):
        def fake_stream_once(messages):
            yield "안녕"
            yield "하세요"

        monkeypatch.setattr(llm_client, "_stream_once", fake_stream_once)

        result = list(llm_client.stream_response_safe([]))
        assert result == ["안녕", "하세요"]

    def test_retry_before_any_token_is_safe(self, monkeypatch):
        """토큰 전송 전 실패는 재시도 가능해야 함"""
        attempts = {"n": 0}

        def fake_stream_once(messages):
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise FakeTransientError("초기 연결 실패")
                yield  # pragma: no cover (제너레이터로 만들기 위한 unreachable yield)
            yield "정상 응답"

        monkeypatch.setattr(llm_client, "_stream_once", fake_stream_once)

        result = list(llm_client.stream_response_safe([]))
        assert result == ["정상 응답"]
        assert attempts["n"] == 2

    def test_exhausts_retries_with_no_tokens_raises_unavailable(self, monkeypatch):
        def fake_stream_once(messages):
            raise FakeTransientError("계속 실패")
            yield  # pragma: no cover

        monkeypatch.setattr(llm_client, "_stream_once", fake_stream_once)

        with pytest.raises(llm_client.LLMUnavailableError):
            list(llm_client.stream_response_safe([]))

    def test_partial_tokens_then_failure_raises_interrupted_without_retry(self, monkeypatch):
        """이미 토큰을 보낸 뒤 실패하면 재시도하지 않고 즉시 중단 처리해야 함 (중복 방지)"""
        attempts = {"n": 0}

        def fake_stream_once(messages):
            attempts["n"] += 1
            yield "일부"
            raise FakeTransientError("중간에 끊김")

        monkeypatch.setattr(llm_client, "_stream_once", fake_stream_once)

        collected = []
        with pytest.raises(llm_client.LLMStreamInterruptedError):
            for token in llm_client.stream_response_safe([]):
                collected.append(token)

        assert collected == ["일부"]
        assert attempts["n"] == 1  # 재시도가 일어나면 안 됨

    def test_fatal_exception_before_tokens_skips_retry_raises_unavailable(self, monkeypatch):
        """인증오류 등 영구적 실패는 토큰 전송 전이라도 재시도 없이 즉시 LLMUnavailableError"""
        attempts = {"n": 0}

        def fake_stream_once(messages):
            attempts["n"] += 1
            raise FakeFatalError("인증 실패")
            yield  # pragma: no cover

        monkeypatch.setattr(llm_client, "_stream_once", fake_stream_once)

        with pytest.raises(llm_client.LLMUnavailableError):
            list(llm_client.stream_response_safe([]))
        assert attempts["n"] == 1  # 재시도 없이 1번만 시도

    def test_fatal_exception_after_tokens_raises_interrupted(self, monkeypatch):
        """인증오류가 스트리밍 중간에 나면(이례적이지만) 중단 처리로 넘어가야 함"""
        def fake_stream_once(messages):
            yield "일부"
            raise FakeFatalError("중간에 인증 만료")

        monkeypatch.setattr(llm_client, "_stream_once", fake_stream_once)

        collected = []
        with pytest.raises(llm_client.LLMStreamInterruptedError):
            for token in llm_client.stream_response_safe([]):
                collected.append(token)
        assert collected == ["일부"]


class TestBuildDegradedFallbackText:
    def test_empty_guidelines_returns_generic_message(self):
        text = llm_client.build_degraded_fallback_text([])
        assert "연락처" in text or "문의" in text

    def test_groups_by_matched_disaster_type(self):
        guidelines = [
            {"matched_disaster_type": "폭염", "cate_nm2": "폭염", "cate_nm3": "발생시 - 일반가정", "content": "물을 마시세요"},
            {"matched_disaster_type": "호우", "cate_nm2": "호우", "cate_nm3": "호우특보중 - 대피", "content": "대피하세요"},
        ]
        text = llm_client.build_degraded_fallback_text(guidelines)
        assert "[폭염]" in text
        assert "[호우]" in text
        assert "물을 마시세요" in text
        assert "대피하세요" in text