from app.agents.meal_agent import run_agent
from app.schemas import UserProfile
from app.services import food_retriever
from app.services.food_retriever import load_foods, retrieve_foods


def test_end_to_end_scenario(monkeypatch):
    """핵심 시나리오가 최종 응답까지 도달하는지.

    retrieve는 CSV 경로로 고정해 외부(Supabase/Upstage) 의존 없이 결정론적으로 돈다.
    """

    # retrieve_foods를 항상 CSV 후보로 돌게 고정 (Supabase 호출 차단)
    def csv_retrieve(conditions, profile, foods=None, relax=False):
        return retrieve_foods(conditions, profile, foods=load_foods(), relax=relax)

    monkeypatch.setattr(food_retriever, "retrieve_foods", csv_retrieve)
    # graph 모듈이 import한 참조도 교체
    monkeypatch.setattr("app.agents.graph.retrieve_foods", csv_retrieve)

    msg = "400kcal 이하로, 계란은 빼고 야채 많은 한 끼 추천해줘"
    state = run_agent(msg, UserProfile(allergies=[]))

    # 조건이 추출됐는지
    assert state.conditions.target_kcal == 400
    assert state.conditions.kcal_mode == "upper"

    # 최종 응답이 생성됐는지
    assert state.final_response != ""

    # 검증 결과가 있는지
    assert state.validation_result is not None
    print("\n" + state.final_response)  # -s 옵션으로 보임


def _csv_only(monkeypatch):
    """멀티턴 테스트도 외부 의존 없이 CSV 경로로 고정."""

    def csv_retrieve(conditions, profile, foods=None, relax=False):
        return retrieve_foods(conditions, profile, foods=load_foods(), relax=relax)

    monkeypatch.setattr(food_retriever, "retrieve_foods", csv_retrieve)
    monkeypatch.setattr("app.agents.graph.retrieve_foods", csv_retrieve)


def test_multiturn_followup_merges_with_previous_turn(monkeypatch):
    """되묻기(need_more_info) 후, 같은 thread로 조건을 주면 이전 턴과 병합해 추천으로 이어간다."""
    _csv_only(monkeypatch)
    tid = "test-multiturn-merge"

    # 턴1: 조건 없는 모호한 요청 → 되묻기
    s1 = run_agent("뭐 먹지?", UserProfile(), thread_id=tid)
    assert s1.intent == "need_more_info"

    # 턴2: 같은 thread로 조건 제공 → 병합해서 추천 진행
    s2 = run_agent("400kcal 얼큰한 국물", UserProfile(), thread_id=tid)
    assert s2.intent == "meal_recommend"
    assert s2.conditions is not None
    assert s2.conditions.target_kcal == 400
    assert s2.final_response != ""


def test_no_thread_id_is_stateless(monkeypatch):
    """thread_id가 없으면 매 호출이 독립(무상태)이라 되묻기는 되묻기로 끝난다."""
    _csv_only(monkeypatch)
    s = run_agent("뭐 먹지?", UserProfile())  # thread_id 없음
    assert s.intent == "need_more_info"


def test_multiturn_threads_are_isolated(monkeypatch):
    """서로 다른 thread_id는 맥락이 섞이지 않는다."""
    _csv_only(monkeypatch)
    run_agent("뭐 먹지?", UserProfile(), thread_id="thread-A")
    # thread-B는 A의 되묻기 맥락과 무관하게 자기 요청대로 분류돼야 한다
    s = run_agent("김치찌개 나트륨 얼마야?", UserProfile(), thread_id="thread-B")
    assert s.intent == "nutrition_query"
