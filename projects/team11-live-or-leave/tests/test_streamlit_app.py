"""streamlit_app.py 고유 로직 단위 테스트.

mock 판단·에이전트 생성 자체(using_mock_llm/mock_llm_reason/build_recommendation_agent)는
app/agent/factory.py로 옮겨 main.py(FastAPI)와 공유한다 — 그 로직의 세부
분기 테스트는 tests/test_agent_factory.py에 있다. 여기서는 Streamlit이 그
공유 로직을 "제대로 가져다 쓰는지"(재노출·캐싱)만 확인한다.

load_agent는 @st.cache_resource가 걸려 있어 테스트 간 캐시가 새면 이전
호출의 인스턴스가 그대로 반환된다 — 매 테스트 전 캐시를 비운다.
"""
from __future__ import annotations

import json

import pytest

import streamlit_app
from app.agent import factory as agent_factory
from app.agent.mock_llm import MockLLM


@pytest.fixture(autouse=True)
def _clear_agent_cache():
    """load_agent()는 @st.cache_resource, run_agent_cached()는 @st.cache_data라
    테스트마다 새로 분기시키려면 이전 호출의 캐시를 비워야 한다."""
    streamlit_app.load_agent.clear()
    streamlit_app.run_agent_cached.clear()
    yield
    streamlit_app.load_agent.clear()
    streamlit_app.run_agent_cached.clear()


# ---------- 공유 팩토리 위임 확인 (세부 분기는 test_agent_factory.py) ----------

def test_using_mock_llm_is_the_shared_factory_function():
    """재구현이 아니라 진짜 같은 함수여야 한다 — main.py와 판단이 갈라지는 걸 방지."""
    assert streamlit_app.using_mock_llm is agent_factory.using_mock_llm


def test_mock_llm_reason_delegates_to_shared_factory(monkeypatch):
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    assert streamlit_app._mock_llm_reason() == agent_factory.mock_llm_reason()


# ---------- load_agent(): st.cache_resource가 실제로 factory 결과를 캐싱하는지 ----------

def test_load_agent_uses_mock_llm_when_no_key(monkeypatch):
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    agent = streamlit_app.load_agent()
    assert isinstance(agent.llm, MockLLM)


def test_load_agent_uses_mock_llm_when_forced_despite_key(monkeypatch):
    monkeypatch.setenv("UPSTAGE_API_KEY", "real-key")
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    agent = streamlit_app.load_agent()
    assert isinstance(agent.llm, MockLLM)


def test_load_agent_uses_real_llm_when_key_present_and_not_forced(monkeypatch):
    """실 API를 호출하지는 않는다 — SolarLLM 생성자는 키를 읽어 저장만 하고
    네트워크 요청은 parse_intent/explain 호출 시점에야 일어난다."""
    monkeypatch.setenv("UPSTAGE_API_KEY", "real-key")
    monkeypatch.delenv("USE_MOCK_LLM", raising=False)
    agent = streamlit_app.load_agent()
    assert not isinstance(agent.llm, MockLLM)
    assert agent.llm.api_key == "real-key"


# ---------- assign_tiers(): 지도 완전성 — 실격 동도 전부 그려야 함 ----------

def test_assign_tiers_renders_every_disqualified_dong():
    """실격 동을 일부만 그리면 나머지가 지도에서 통째로 사라져 구멍이 뚫린다.
    필수 필터로 수백 개가 실격돼도(예: 클라이밍장 없는 동 333개) 전부
    disqualified 티어로 포함돼야 한다."""
    recs = [{
        "gu": "강남구", "dong": f"추천{i}동", "total_score": 0.9 - i * 0.01,
        "scores": {"code": f"R{i}", "raw": dict(
            crime_rate=1.0, cctv_cnt=1, conv_cnt=1, mart_cnt=1,
            hosp_cnt=1, bus_cnt=1, subway_access=0.5, park_cnt=1)},
    } for i in range(3)]
    disq = [{"code": f"D{i}", "gu": "강북구", "dong": f"실격{i}동", "missing": ["클라이밍"]}
            for i in range(300)]

    df = streamlit_app.assign_tiers(recs, disq)

    assert len(df) == 3 + 300  # 하나도 빠지면 안 됨
    assert (df["tier"] == "disqualified").sum() == 300


# ---------- run_agent_cached(): 같은 입력이면 LLM 재호출 금지 ----------

def test_run_agent_cached_calls_llm_only_once_for_same_input(monkeypatch):
    """Streamlit rerun마다 같은 텍스트로 parse_intent+explain이 재호출되는 걸
    막는 게 이 캐시의 존재 이유다. 같은 (텍스트, mock여부, 필터) 키로 두 번
    불러도 agent.run은 한 번만 실행돼야 한다."""
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    calls = {"n": 0}
    real_run = streamlit_app.RecommendationAgent.run

    def counting_run(self, user_text, top_n=3, required_filters=None):
        calls["n"] += 1
        return real_run(self, user_text, top_n=top_n, required_filters=required_filters)

    monkeypatch.setattr(streamlit_app.RecommendationAgent, "run", counting_run)
    v = streamlit_app.PIPELINE_VERSION
    streamlit_app.run_agent_cached("안전한 곳", False, v, "[]")
    streamlit_app.run_agent_cached("안전한 곳", False, v, "[]")
    assert calls["n"] == 1


def test_run_agent_cached_distinguishes_mock_flag_in_cache_key(monkeypatch):
    """mock으로 계산한 결과가 실 LLM 모드에서 재사용되면 안 되므로
    mock 여부가 캐시 키에 포함돼야 한다 — 같은 텍스트라도 플래그가 다르면 재실행."""
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    calls = {"n": 0}
    real_run = streamlit_app.RecommendationAgent.run

    def counting_run(self, user_text, top_n=3, required_filters=None):
        calls["n"] += 1
        return real_run(self, user_text, top_n=top_n, required_filters=required_filters)

    monkeypatch.setattr(streamlit_app.RecommendationAgent, "run", counting_run)
    v = streamlit_app.PIPELINE_VERSION
    streamlit_app.run_agent_cached("안전한 곳", True, v, "[]")
    streamlit_app.run_agent_cached("안전한 곳", False, v, "[]")
    assert calls["n"] == 2


def test_run_agent_cached_invalidates_on_pipeline_version_bump(monkeypatch):
    """하위 모듈(필터·스코어링) 코드가 바뀌어도 st.cache_data는 모른다 —
    PIPELINE_VERSION을 키에 넣어 버전이 오르면 낡은 결과를 버리게 한다."""
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    calls = {"n": 0}
    real_run = streamlit_app.RecommendationAgent.run

    def counting_run(self, user_text, top_n=3, required_filters=None):
        calls["n"] += 1
        return real_run(self, user_text, top_n=top_n, required_filters=required_filters)

    monkeypatch.setattr(streamlit_app.RecommendationAgent, "run", counting_run)
    streamlit_app.run_agent_cached("안전한 곳", False, 1, "[]")
    streamlit_app.run_agent_cached("안전한 곳", False, 2, "[]")
    assert calls["n"] == 2


def test_run_agent_cached_distinguishes_required_filters_in_cache_key(monkeypatch):
    """구조화 필터(구·기준 장소)가 다르면 같은 선호 텍스트라도 재실행돼야
    한다 — required_filters_json도 캐시 키의 일부다."""
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    calls = {"n": 0}
    real_run = streamlit_app.RecommendationAgent.run

    def counting_run(self, user_text, top_n=3, required_filters=None):
        calls["n"] += 1
        return real_run(self, user_text, top_n=top_n, required_filters=required_filters)

    monkeypatch.setattr(streamlit_app.RecommendationAgent, "run", counting_run)
    v = streamlit_app.PIPELINE_VERSION
    streamlit_app.run_agent_cached("안전한 곳", False, v, "[]")
    streamlit_app.run_agent_cached(
        "안전한 곳", False, v, json.dumps([{"type": "gu", "gu": ["강남구"]}]))
    assert calls["n"] == 2


def test_load_agent_result_is_cached_across_calls(monkeypatch):
    """st.cache_resource이므로 같은 프로세스 내 재호출은 새 인스턴스를 만들지 않고
    캐시된 동일 객체를 반환해야 한다 (매 rerun마다 에이전트를 새로 만들지 않기 위함)."""
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    first = streamlit_app.load_agent()
    second = streamlit_app.load_agent()
    assert first is second
