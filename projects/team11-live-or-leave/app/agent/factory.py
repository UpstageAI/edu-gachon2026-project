"""RecommendationAgent 생성/mock 판단 단일 진입점.

main.py(FastAPI)와 streamlit_app.py가 각자 RecommendationAgent()를 만들고,
"키 없으면 mock으로 낮춘다"는 안전장치도 Streamlit에만 있던 걸 여기로 합친다.
그 결과 두 앱이 같은 입력(환경변수)에 항상 같은 결정을 내린다.

- build_recommendation_agent(): 호출할 때마다 새로 만든다. 캐싱은 호출자
  책임 — Streamlit은 @st.cache_resource로, 여기 자체 싱글턴을 쓰는 쪽
  (get_recommendation_agent)은 그 결과를 재사용한다.
- get_recommendation_agent(): 캐싱 데코레이터가 없는 곳(main.py) 전용
  프로세스 지연 싱글턴. 요청마다 CsvDongRepository를 다시 읽지 않기 위함.
"""
from __future__ import annotations

import os

from app.agent.loop import RecommendationAgent
from app.agent.mock_llm import MockLLM


def using_mock_llm() -> bool:
    """UPSTAGE_API_KEY가 없거나 USE_MOCK_LLM으로 강제됐으면 True.

    UPSTAGE_API_KEY가 없는 환경(로컬 UI 개발 등)에서 그대로 두면 API 호출이
    실패하므로 자동으로 MockLLM으로 낮춘다. 키가 있어도 레이아웃·색깔 확인처럼
    빠른 반복 작업만 할 땐 USE_MOCK_LLM=1로 강제로 mock을 쓸 수 있다.

    환경변수 값은 문자열이라 bool()만으로는 "0"도 참으로 취급돼버린다 —
    "1"/"true"일 때만 강제 mock으로 인정한다."""
    return not os.environ.get("UPSTAGE_API_KEY") or os.environ.get("USE_MOCK_LLM", "").lower() in ("1", "true")


def mock_llm_reason() -> str:
    if not os.environ.get("UPSTAGE_API_KEY"):
        return "UPSTAGE_API_KEY 없음"
    return "USE_MOCK_LLM 설정됨"


def build_recommendation_agent() -> RecommendationAgent:
    """using_mock_llm() 판단에 따라 RecommendationAgent를 새로 만든다."""
    return RecommendationAgent(llm=MockLLM()) if using_mock_llm() else RecommendationAgent()


_agent: RecommendationAgent | None = None


def get_recommendation_agent() -> RecommendationAgent:
    """프로세스 수명 동안 1회만 생성해 재사용하는 지연 싱글턴 (main.py 전용).

    Streamlit은 자체 캐시(@st.cache_resource)가 있어 build_recommendation_agent()를
    직접 쓰고, 캐싱 데코레이터가 없는 FastAPI 쪽만 이 싱글턴을 쓴다."""
    global _agent
    if _agent is None:
        _agent = build_recommendation_agent()
    return _agent
