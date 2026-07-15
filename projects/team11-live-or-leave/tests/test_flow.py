"""흐름 검증 테스트 (행정동 단위).

RecommendationAgent 기본값은 실제 Solar API이므로, 여기서는 흐름(가중치·랭킹·
되묻기 분기) 자체를 빠르고 결정론적으로 검증하기 위해 MockLLM을 명시적으로
주입한다. 실제 Solar API 응답 품질 검증은 demo.py로 수동 확인한다.
"""
from __future__ import annotations

from app.agent.loop import RecommendationAgent
from app.agent.mock_llm import MockLLM
from app.data.csv_repository import CsvDongRepository
from app.schemas.tools import CategoryPreference, Importance
from app.services import scoring


def _agent() -> RecommendationAgent:
    return RecommendationAgent(llm=MockLLM())


def test_weights_sum_to_one():
    pref = CategoryPreference(
        safety=Importance.VERY_HIGH, convenience=Importance.HIGH,
        mobility=Importance.MEDIUM, environment=Importance.NONE)
    w = scoring.preference_to_weights(pref)
    assert abs(sum(w.values()) - 1.0) < 1e-9
    print("✓ 가중치 합 = 1")


def test_within_gu_discrimination():
    """같은 구 안 행정동이 서로 다른 점수를 받는지 (MAUP 해결 확인)."""
    repo = CsvDongRepository()
    scores = scoring.score_dongs(repo.all_metrics())
    gangnam = [s for s in scores if s.gu == "강남구"]
    conv_vals = {s.convenience for s in gangnam}
    assert len(conv_vals) > 1, "같은 구 내 행정동이 전부 동일 점수 (변별 실패)"
    print(f"✓ 구 내 행정동 변별 (강남구 편의 점수 {len(conv_vals)}종)")


def test_preference_changes_ranking():
    agent = _agent()
    a = agent.run("공원 많고 조용한 동네")
    b = agent.run("지하철 교통 편한 곳 야근")
    assert a.data["weights"] != b.data["weights"]
    print(f"✓ 성향별 결과 차이 (환경1위={a.data['recommendations'][0]['dong']}, "
          f"이동1위={b.data['recommendations'][0]['dong']})")


def test_clarification():
    agent = _agent()
    assert agent.run("아무데나 좋은 곳").kind == "clarify"
    print("✓ 모호한 입력 → 되묻기")


def test_deterministic():
    agent = _agent()
    t = "안전하고 지하철 가까운 곳"
    r1 = [x["dong"] for x in agent.run(t).data["recommendations"]]
    r2 = [x["dong"] for x in agent.run(t).data["recommendations"]]
    assert r1 == r2
    print("✓ 동일 입력 → 동일 결과")


if __name__ == "__main__":
    test_weights_sum_to_one()
    test_within_gu_discrimination()
    test_preference_changes_ranking()
    test_clarification()
    test_deterministic()
    print("\n모든 흐름 검증 통과")
