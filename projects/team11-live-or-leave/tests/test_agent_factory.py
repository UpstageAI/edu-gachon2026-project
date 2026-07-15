"""app/agent/factory.py 단위 테스트 — main.py(FastAPI)와 streamlit_app.py가
공유하는 mock 판단·에이전트 생성 로직.

전에는 이 로직이 streamlit_app.py에만 있었고 main.py는 항상 실 API를 썼다
(키 없으면 그냥 에러). 지금은 둘 다 여기 하나로 판단한다 — 그래서 이 로직
자체는 "Streamlit 전용"이 아니라 앱 중립적으로 테스트한다.

관점:
  - 기능(정상 분기): 키 유무 × USE_MOCK_LLM 유무 4가지 조합
  - 경계값: 빈 문자열 환경변수는 "설정 안 함"과 같다 (bool("") == False)
  - 보안: mock_llm_reason()이 실제 API 키 값을 절대 노출하지 않는지
  - build_recommendation_agent()가 판단대로 실제 llm 타입을 고르는지
"""
from __future__ import annotations

from app.agent.factory import build_recommendation_agent, mock_llm_reason, using_mock_llm
from app.agent.mock_llm import MockLLM


# ---------- using_mock_llm(): 키 유무 × 강제 mock 4가지 조합 ----------

def test_using_mock_llm_true_when_no_key(monkeypatch):
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    monkeypatch.delenv("USE_MOCK_LLM", raising=False)
    assert using_mock_llm() is True


def test_using_mock_llm_false_when_key_present_and_not_forced(monkeypatch):
    monkeypatch.setenv("UPSTAGE_API_KEY", "real-key")
    monkeypatch.delenv("USE_MOCK_LLM", raising=False)
    assert using_mock_llm() is False


def test_using_mock_llm_true_when_key_present_but_forced(monkeypatch):
    monkeypatch.setenv("UPSTAGE_API_KEY", "real-key")
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    assert using_mock_llm() is True


def test_using_mock_llm_true_when_no_key_and_forced(monkeypatch):
    """키도 없고 강제 플래그도 있는 경우 — 두 조건 중 하나만 있어도 mock이어야 한다."""
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    assert using_mock_llm() is True


# ---------- 경계값: 빈 문자열 환경변수 ----------

def test_using_mock_llm_empty_string_flag_does_not_force_mock(monkeypatch):
    """USE_MOCK_LLM=''(빈 문자열)은 '설정함'이 아니라 '설정 안 함'과 같다
    (bool("") == False). 셸에서 `USE_MOCK_LLM= streamlit run ...`처럼 빈 값으로
    export해도 강제 mock이 켜지지 않는다는, 직관과 다를 수 있는 실제 동작."""
    monkeypatch.setenv("UPSTAGE_API_KEY", "real-key")
    monkeypatch.setenv("USE_MOCK_LLM", "")
    assert using_mock_llm() is False


def test_using_mock_llm_string_zero_does_not_force_mock(monkeypatch):
    """USE_MOCK_LLM="0"은 "끄겠다"는 의도이므로 강제 mock이 켜지면 안 된다.

    환경변수는 항상 문자열이라 bool("0")은 파이썬에서 True다 — 순진하게
    bool()로만 판단하면 "0"도 "설정됨"으로 오인해 정반대로 동작하는 버그가
    난다. .env에 USE_MOCK_LLM=0을 써서 실 API를 쓰려 했는데 계속 mock으로
    떨어지던 실제 사고에서 발견됨."""
    monkeypatch.setenv("UPSTAGE_API_KEY", "real-key")
    monkeypatch.setenv("USE_MOCK_LLM", "0")
    assert using_mock_llm() is False


# ---------- mock_llm_reason(): 사유 문구 + 키 노출 금지 ----------

def test_mock_llm_reason_reports_missing_key(monkeypatch):
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    assert mock_llm_reason() == "UPSTAGE_API_KEY 없음"


def test_mock_llm_reason_reports_forced_flag_when_key_present(monkeypatch):
    monkeypatch.setenv("UPSTAGE_API_KEY", "real-key")
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    assert mock_llm_reason() == "USE_MOCK_LLM 설정됨"


def test_mock_llm_reason_never_leaks_the_actual_api_key(monkeypatch):
    """화면·API 응답에 그대로 노출될 수 있는 문구이므로, 키 값 자체가
    절대 섞여 들어가면 안 된다."""
    secret = "up_9gHwvBT5FPWMm55dxRcTO6SUmFWt1"
    monkeypatch.setenv("UPSTAGE_API_KEY", secret)
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    assert secret not in mock_llm_reason()


# ---------- build_recommendation_agent(): 실제 llm 타입 분기 ----------

def test_build_agent_uses_mock_llm_when_no_key(monkeypatch):
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    agent = build_recommendation_agent()
    assert isinstance(agent.llm, MockLLM)


def test_build_agent_uses_mock_llm_when_forced_despite_key(monkeypatch):
    monkeypatch.setenv("UPSTAGE_API_KEY", "real-key")
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    agent = build_recommendation_agent()
    assert isinstance(agent.llm, MockLLM)


def test_build_agent_uses_real_llm_when_key_present_and_not_forced(monkeypatch):
    """실 API를 호출하지는 않는다 — SolarLLM 생성자는 키를 읽어 저장만 하고
    네트워크 요청은 parse_intent/explain 호출 시점에야 일어난다."""
    monkeypatch.setenv("UPSTAGE_API_KEY", "real-key")
    monkeypatch.delenv("USE_MOCK_LLM", raising=False)
    agent = build_recommendation_agent()
    assert not isinstance(agent.llm, MockLLM)
    assert agent.llm.api_key == "real-key"


def test_build_agent_always_constructs_fresh_instance(monkeypatch):
    """get_recommendation_agent()(main.py용 싱글턴)와 달리, 이건 캐싱하면 안 된다 —
    캐싱은 각 호출자(Streamlit의 st.cache_resource 등) 책임이라서."""
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    assert build_recommendation_agent() is not build_recommendation_agent()


# ---------- get_recommendation_agent(): main.py용 프로세스 싱글턴 ----------

def test_get_recommendation_agent_returns_same_instance_across_calls(monkeypatch):
    import app.agent.factory as factory

    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    monkeypatch.setattr(factory, "_agent", None)  # 다른 테스트가 채워둔 싱글턴 초기화
    first = factory.get_recommendation_agent()
    second = factory.get_recommendation_agent()
    assert first is second
