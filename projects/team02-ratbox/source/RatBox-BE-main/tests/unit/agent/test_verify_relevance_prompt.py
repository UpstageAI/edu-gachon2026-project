from app.agent.prompts.verify_relevance_prompt import build_verify_relevance_prompt
from app.domain.models import RecipeCandidate


def test_prompt_shows_matched_and_missing_ingredients_separately():
    """verify_relevance가 "왜 매칭됐는지" 모른 채 판단하던 문제(소금만 겹쳐도 판단
    불가) 수정 확인: 겹치는 재료와 부족한 재료를 프롬프트에 각각 명시해야 한다."""
    candidate = RecipeCandidate(
        id="1",
        name="전복죽",
        matched_ingredients=["소금"],
        missing_ingredients=["전복", "찹쌀"],
    )

    prompt = build_verify_relevance_prompt(["소금", "감자", "우유"], [candidate])

    assert "겹치는 재료: 소금" in prompt
    assert "부족한 재료: 전복, 찹쌀" in prompt


def test_prompt_shows_none_marker_for_no_overlap():
    candidate = RecipeCandidate(id="1", name="레시피", matched_ingredients=[])

    prompt = build_verify_relevance_prompt(["소금"], [candidate])

    assert "겹치는 재료: 없음" in prompt


def test_prompt_shows_placeholder_when_no_candidates():
    prompt = build_verify_relevance_prompt(["소금"], [])

    assert "(없음)" in prompt
