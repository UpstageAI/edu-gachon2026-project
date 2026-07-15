import json

from fastapi.testclient import TestClient

from app.agent import graph as graph_module
from app.agent.nodes import classify_and_substitute as classify_module
from app.agent.nodes import resolve_inputs as resolve_inputs_module
from app.agent.services import relevance_service, search_service
from app.agent.services.relevance_service import VerifyRelevanceOutput
from app.agent.tools.schemas import (
    ClassifyMissingOutput,
    FindSubstitutesOutput,
    GenerateCookingStepsOutput,
)
from app.api.routes import recommend as recommend_module
from app.domain.models import SubstituteCandidate
from app.main import app

client = TestClient(app)


def _sse_events(text: str) -> list[tuple[str, dict]]:
    """`/recommend`가 SSE로 흘려보낸 본문을 (event, data) 목록으로 파싱한다."""
    events = []
    for raw in text.split("\n\n"):
        if not raw.strip():
            continue
        event = "message"
        data = None
        for line in raw.splitlines():
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        if data is not None:
            events.append((event, json.loads(data)))
    return events


def _final_payload(response) -> dict:
    events = _sse_events(response.text)
    final = next(data for event, data in events if event == "final")
    return final


def _patch_search_phase(
    monkeypatch,
    *,
    allergies=None,
    ingredients_by_recipe=None,
    recipes_by_id=None,
    verify_results=None,
):
    """resolve_inputs, search_service, relevance_service를 스텁으로 대체한다.

    ingredients_by_recipe/recipes_by_id는 항상 "시도 순서 리스트"로 받는다 (broaden_search로
    재검색할 때마다 순서대로 다음 항목을 쓴다). 재시도가 없는 테스트도 원소 1개짜리 리스트로
    감싸서 넘긴다 - 단일 값이 우연히 list 타입(레시피 목록)일 때의 모호함을 피하기 위함.
    """
    monkeypatch.setattr(resolve_inputs_module, "get_ingredient_names_by_ids", lambda ids: ids)
    monkeypatch.setattr(
        resolve_inputs_module, "get_allergen_names_by_ids", lambda ids: allergies or []
    )
    # 응답 경계에서 카테고리를 붙이는 조회 - 이 시나리오 테스트들은 카테고리 값 자체를
    # 검증하지 않으므로 빈 매핑으로 스텁한다.
    monkeypatch.setattr(recommend_module, "get_ingredient_categories_by_names", lambda names: {})

    # search_recipes()가 호출될 때마다(1차 검색, broaden_search 후 재검색, ...) 순서대로
    # 다른 데이터를 주기 위한 공유 인덱스. find_recipe_ingredient_matches가 매
    # search_recipes() 호출마다 정확히 한 번 불리므로 거기서만 증가시킨다.
    call_index = {"n": -1}
    ingredients_sequence = ingredients_by_recipe if ingredients_by_recipe is not None else [{}]
    recipes_sequence = recipes_by_id if recipes_by_id is not None else [[]]

    def _current_idx() -> int:
        return min(max(call_index["n"], 0), len(ingredients_sequence) - 1)

    def _find_recipe_ingredient_matches(ids):
        call_index["n"] += 1
        idx = _current_idx()
        # 실제 쿼리는 ingredient_id in ids로 필터링된 행만 돌려주므로, 선택되지 않은
        # 재료는 여기서도 걸러낸다 (테스트 데이터는 id==name이라 이름으로 비교한다).
        selected = set(ids)
        matches = {
            recipe_id: [row["name"] for row in rows if row["name"] in selected]
            for recipe_id, rows in ingredients_sequence[idx].items()
        }
        return {recipe_id: names for recipe_id, names in matches.items() if names}

    def _get_recipe_ingredient_names(recipe_id):
        return ingredients_sequence[_current_idx()][recipe_id]

    def _get_recipes_by_ids(ids):
        return recipes_sequence[_current_idx()]

    monkeypatch.setattr(
        search_service, "find_recipe_ingredient_matches", _find_recipe_ingredient_matches
    )
    monkeypatch.setattr(search_service, "get_recipes_by_ids", _get_recipes_by_ids)
    # 이 시나리오 테스트들은 재료 가중치/핵심재료 판별 로직 자체를 검증하지 않으므로,
    # 모든 재료를 희귀(코어) 재료로 취급해 기존 매칭개수 기준 동작이 그대로 보이게 한다.
    monkeypatch.setattr(
        search_service, "compute_document_frequency_ratios", lambda ids: {i: 0.0 for i in ids}
    )

    # rank_candidates(기존, 변경 없음)도 recipe_service.get_recipe_ingredient_names를 쓴다.
    from app.agent.services import recipe_service

    monkeypatch.setattr(
        recipe_service, "get_recipe_ingredient_names", _get_recipe_ingredient_names
    )

    verify_sequence = verify_results if verify_results is not None else [
        VerifyRelevanceOutput(passed=True, reason="적절해요")
    ]
    verify_calls = {"n": 0}

    def _verify(selected_ingredients, candidates):
        call_n = verify_calls["n"]
        verify_calls["n"] += 1
        # 실제 relevance_service.verify()와 동일하게, 후보가 비어있으면 항상 실패로 처리한다.
        if not candidates:
            return VerifyRelevanceOutput(passed=False, reason="후보가 없어요")
        idx = min(call_n, len(verify_sequence) - 1)
        return verify_sequence[idx]

    monkeypatch.setattr(relevance_service, "verify", _verify)
    return verify_calls


def test_normal_flow_returns_top_recipes(monkeypatch):
    _patch_search_phase(
        monkeypatch,
        ingredients_by_recipe=[
            {
                "1": [{"name": "계란"}],
                "2": [{"name": "계란"}, {"name": "대파"}],
            }
        ],
        recipes_by_id=[
            [
                {"id": "1", "name": "계란밥", "cooking_time": 10},
                {"id": "2", "name": "대파계란찜", "cooking_time": 20},
            ]
        ],
    )

    response = client.post("/recommend", json={"ingredient_ids": ["계란"]})

    assert response.status_code == 200
    body = _final_payload(response)
    assert {r["name"] for r in body["recipes"]} == {"계란밥", "대파계란찜"}


def test_streams_status_events_before_final(monkeypatch):
    """노드가 끝날 때마다 status 이벤트가 흘러나오고, 마지막에 final+done이 온다."""
    _patch_search_phase(
        monkeypatch,
        ingredients_by_recipe=[{"1": [{"name": "계란"}]}],
        recipes_by_id=[[{"id": "1", "name": "계란밥", "cooking_time": 10}]],
    )

    response = client.post("/recommend", json={"ingredient_ids": ["계란"]})

    events = _sse_events(response.text)
    event_names = [event for event, _ in events]
    assert "status" in event_names
    assert event_names[-2:] == ["final", "done"]
    status_nodes = {data["node"] for event, data in events if event == "status"}
    assert "search_recipes" in status_nodes
    assert "respond" in status_nodes


def test_zero_matching_recipes_asks_clarification_after_broadening(monkeypatch):
    """검색이 완화해도 후보를 하나도 못 찾으면 재료 추가를 요청한다."""
    _patch_search_phase(monkeypatch, ingredients_by_recipe=[{}], recipes_by_id=[[]])

    state = graph_module.run_agent(
        ingredient_ids=["없는재료"], allergen_ids=[], recipe_id=None
    )

    assert state.candidate_recipes == []
    assert "재료를 몇 가지 더 알려주시면" in state.final_message


def test_verify_relevance_failure_broadens_search_and_succeeds(monkeypatch):
    """1차 검색 결과가 검증에 실패하면 조건을 완화해 재검색하고, 그걸로 통과하면 그 결과를 쓴다."""
    verify_calls = _patch_search_phase(
        monkeypatch,
        ingredients_by_recipe=[
            {},  # 1차: min_match=2 -> 후보 없음
            {"1": [{"name": "양파"}]},  # 2차(완화 후): min_match=1 -> 후보 있음
        ],
        recipes_by_id=[
            [],
            [{"id": "1", "name": "양파계란찜", "cooking_time": 15}],
        ],
        verify_results=[
            VerifyRelevanceOutput(passed=False, reason="후보가 없어요"),
            VerifyRelevanceOutput(passed=True, reason="적절해요"),
        ],
    )

    state = graph_module.run_agent(ingredient_ids=["양파"], allergen_ids=[], recipe_id=None)

    assert verify_calls["n"] == 2
    assert [c.name for c in state.candidate_recipes] == ["양파계란찜"]


def test_best_effort_response_when_retries_exhausted_but_candidate_exists(monkeypatch):
    """완화해도 관련성 검증에 계속 실패하지만 후보가 있으면, 단서를 달아 최선의 답을 준다."""
    _patch_search_phase(
        monkeypatch,
        ingredients_by_recipe=[{"1": [{"name": "트러플"}]}],
        recipes_by_id=[[{"id": "1", "name": "트러플리조또", "cooking_time": 30}]],
        verify_results=[
            VerifyRelevanceOutput(passed=False, reason="재료 활용도가 낮아 보여요"),
            VerifyRelevanceOutput(passed=False, reason="여전히 낮아 보여요"),
        ],
    )

    state = graph_module.run_agent(
        ingredient_ids=["트러플"], allergen_ids=[], recipe_id=None
    )

    assert "정확히 맞는 레시피는 못 찾았지만" in state.final_message
    assert "트러플리조또" in state.final_message
    assert state.low_confidence is True


def test_allergy_violation_attempt_excludes_candidate(monkeypatch):
    _patch_search_phase(
        monkeypatch,
        allergies=["새우"],
        ingredients_by_recipe=[
            {
                "1": [{"name": "새우"}, {"name": "밥"}],
                "2": [{"name": "계란"}, {"name": "밥"}],
            }
        ],
        recipes_by_id=[
            [
                {"id": "1", "name": "새우볶음밥", "cooking_time": 10},
                {"id": "2", "name": "계란밥", "cooking_time": 10},
            ]
        ],
    )

    state = graph_module.run_agent(
        ingredient_ids=["밥"], allergen_ids=["새우-allergen-id"], recipe_id=None
    )

    assert [c.id for c in state.candidate_recipes] == ["2"]


def test_substitute_allergy_conflict_is_flagged_not_auto_suggested(monkeypatch):
    monkeypatch.setattr(
        resolve_inputs_module, "get_allergen_names_by_ids", lambda ids: ["새우"]
    )
    monkeypatch.setattr(resolve_inputs_module, "get_ingredient_names_by_ids", lambda ids: ids)
    monkeypatch.setattr(recommend_module, "get_ingredient_categories_by_names", lambda names: {})
    monkeypatch.setattr(
        classify_module,
        "get_recipe_by_id",
        lambda recipe_id: {
            "id": "2",
            "name": "대파계란찜",
            "cooking_time": 15,
            "difficulty": "초급",
            "category": "반찬",
            "cooking_method": "찜",
        },
    )
    monkeypatch.setattr(
        classify_module,
        "get_recipe_ingredient_names",
        lambda recipe_id: [
            {"name": "계란", "is_required": True},
            {"name": "대파", "is_required": True},
        ],
    )
    monkeypatch.setattr(
        classify_module.classification_service,
        "classify",
        lambda recipe_id, available: ClassifyMissingOutput(
            required=["대파"], optional=[], reason="향을 위한 필수 재료"
        ),
    )
    monkeypatch.setattr(
        classify_module.substitute_service,
        "find",
        lambda ingredient_name, recipe_name, recipe_context, exclude_ingredients=None,
        owned_ingredients=None: (
            FindSubstitutesOutput(
                substitutes=[SubstituteCandidate(ingredient_name="대파", substitute_name="새우")],
                reason="테스트",
            )
        ),
    )
    monkeypatch.setattr(
        classify_module.steps_service,
        "generate",
        lambda recipe_name, category, cooking_method, ingredients: GenerateCookingStepsOutput(
            steps=["계란과 대파를 손질한다.", "찜기에 넣고 익힌다."]
        ),
    )

    state = graph_module.run_agent(
        ingredient_ids=["계란"], allergen_ids=["새우-allergen-id"], recipe_id="2"
    )

    assert len(state.substitutes) == 1
    assert state.substitutes[0].allergy_conflict is True
    assert "괜찮으실까요" in state.final_message
