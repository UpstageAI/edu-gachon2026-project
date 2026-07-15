"""실패 케이스 처리 테스트.
Solar 호출이 어떤 이유(인증 오류·요청 한도·타임아웃·연결 오류·알 수 없는 오류)로
실패하더라도 예외가 새지 않고 항상 Mock 규칙으로 안전하게 폴백해야 한다.
"""
import litellm.exceptions as exc
import pytest
from app.agent.graph import tutor_turn
from app.core import config, llm_client
from app.repositories import problem_repo

P = problem_repo.get_problem("arith_001")

ERRORS = [
    exc.AuthenticationError(message="bad key", llm_provider="openai", model="solar-pro2"),
    exc.RateLimitError(message="rate limited", llm_provider="openai", model="solar-pro2"),
    exc.Timeout(message="timed out", model="solar-pro2", llm_provider="openai"),
    exc.APIConnectionError(message="conn refused", llm_provider="openai", model="solar-pro2"),
    ValueError("전혀 예상 못한 에러"),
]


@pytest.mark.parametrize("error", ERRORS, ids=lambda e: type(e).__name__)
def test_chat_json_falls_back_on_various_errors(monkeypatch, error, caplog):
    monkeypatch.setattr(config, "USE_LLM", True)
    monkeypatch.setattr(llm_client, "_call", lambda *a, **kw: (_ for _ in ()).throw(error))

    with caplog.at_level("WARNING"):
        result = llm_client.chat_json("sys", "user")

    assert result is None                       # 예외가 새지 않고 안전하게 None 반환
    assert "Mock 폴백" in caplog.text


@pytest.mark.parametrize("error", ERRORS, ids=lambda e: type(e).__name__)
def test_chat_text_falls_back_on_various_errors(monkeypatch, error):
    monkeypatch.setattr(config, "USE_LLM", True)
    monkeypatch.setattr(llm_client, "_call", lambda *a, **kw: (_ for _ in ()).throw(error))
    assert llm_client.chat_text("sys", "user") is None


def test_full_scenario_survives_llm_outage(monkeypatch):
    """Solar가 완전히 다운돼도(모든 호출이 예외) 핵심 시나리오는 Mock으로 끝까지 정상 동작해야 한다."""
    monkeypatch.setattr(config, "USE_LLM", True)
    monkeypatch.setattr(
        llm_client, "_call",
        lambda *a, **kw: (_ for _ in ()).throw(
            exc.APIConnectionError(message="down", llm_provider="openai", model="solar-pro2")
        ),
    )
    out = tutor_turn(P, "9명이요")
    assert out["response"]
    assert out["diagnosis"]["solved"] is True
