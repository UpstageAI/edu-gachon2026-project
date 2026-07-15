"""
tools/resilience.py의 call_with_retry 유닛테스트.
LLM 3단 방어(app/llm_client.py)와 동일한 패턴을 DB/외부API 도구에도 적용한 것 검증.
"""
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import pytest
from tools.resilience import call_with_retry, ToolUnavailableError


class FakeTransientError(Exception):
    pass


class FakeFatalError(Exception):
    pass


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    import tools.resilience as resilience_module
    monkeypatch.setattr(resilience_module.time, "sleep", lambda *_: None)


class TestCallWithRetry:
    def test_success_first_try(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            return "ok"

        assert call_with_retry(fn, retryable_exceptions=(FakeTransientError,)) == "ok"
        assert calls["n"] == 1

    def test_retry_then_success(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] < 2:
                raise FakeTransientError("일시 오류")
            return "ok"

        result = call_with_retry(fn, retryable_exceptions=(FakeTransientError,))
        assert result == "ok"
        assert calls["n"] == 2

    def test_exhausts_retries_raises_tool_unavailable(self):
        def fn():
            raise FakeTransientError("계속 실패")

        with pytest.raises(ToolUnavailableError):
            call_with_retry(fn, retryable_exceptions=(FakeTransientError,))

    def test_non_retryable_exception_propagates_immediately_without_wrapping(self):
        """retryable_exceptions에 없는 예외는 재시도/래핑 없이 그대로 전파돼야 함"""
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise FakeFatalError("영구 오류")

        with pytest.raises(FakeFatalError):
            call_with_retry(fn, retryable_exceptions=(FakeTransientError,))
        assert calls["n"] == 1  # 재시도 없이 즉시 전파

    def test_args_and_kwargs_passed_through(self):
        def fn(a, b, c=None):
            return (a, b, c)

        result = call_with_retry(fn, 1, 2, c=3, retryable_exceptions=(FakeTransientError,))
        assert result == (1, 2, 3)

    def test_tool_name_included_in_error_message(self):
        def fn():
            raise FakeTransientError("실패")

        with pytest.raises(ToolUnavailableError, match="my-tool"):
            call_with_retry(fn, retryable_exceptions=(FakeTransientError,), tool_name="my-tool")