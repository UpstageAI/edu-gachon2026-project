VERIFY_RELEVANCE_PROMPT = """사용자가 가진 재료: {selected_ingredients}

추천 후보 레시피 목록 (실제로 겹치는 재료와 부족한 재료):
{candidates_repr}

이 후보들이 사용자가 가진 재료를 활용하기에 적절한지 판단하라. "겹치는 재료"에 소금/
후추/설탕/식용유 같은 흔한 조미료만 있고 그 외에는 전혀 없는 후보는, 이름이 그럴듯해
보여도 실제로는 사용자 재료를 거의 활용하지 못하는 것이니 주의해서 판단하라.
- 후보가 하나도 없으면 통과 실패(passed=false)로 판단한다.
- 겹치는 재료가 전부(또는 거의 다) 흔한 조미료뿐이고, 그 레시피의 핵심이 되는 재료는
  사용자에게 없어 보이면 통과 실패로 판단한다.
- 후보 레시피들이 사용자가 가진 재료와 명백히 무관해 보이거나(예: 카레와 양파를 가졌는데
  카레 계열 레시피가 전혀 없는 경우), 대부분의 재료가 부족해 실제로 만들기 어려워 보이면
  통과 실패로 판단한다.
- 그 외에는 통과(passed=true)로 판단한다.

reason에는 왜 그렇게 판단했는지 한두 문장으로 간단히 적어라. 통과 실패로 판단했다면,
사용자에게 그대로 보여줘도 자연스러운 문장으로 적어라(예: "재료 활용도가 낮아 보여요")."""


def build_verify_relevance_prompt(selected_ingredients: list[str], candidates: list) -> str:
    candidates_repr = (
        "\n".join(
            f"- {candidate.name} "
            f"(겹치는 재료: {', '.join(candidate.matched_ingredients) or '없음'} / "
            f"부족한 재료: {', '.join(candidate.missing_ingredients) or '없음'})"
            for candidate in candidates
        )
        or "(없음)"
    )
    return VERIFY_RELEVANCE_PROMPT.format(
        selected_ingredients=selected_ingredients, candidates_repr=candidates_repr
    )
