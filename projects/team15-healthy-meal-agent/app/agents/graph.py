"""
app/agents/graph.py
추천 흐름을 LangGraph StateGraph로 관리한다.
services는 그대로 호출하고, 이 파일은 노드 연결과 재시도 라우팅만 담당한다.
"""

from collections.abc import Callable, Iterator
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.schemas import (
    AgentState,
    FoodItem,
    IntentType,
    MealPlan,
    NutritionTotal,
    UserConditions,
    UserProfile,
    ValidationResult,
)
from app.services.condition_extractor import extract_conditions_stub
from app.services.food_retriever import retrieve_foods
from app.services.intent_router import classify_intent_stub
from app.services.meal_composer import compose_meal
from app.services.nutrition_calculator import calculate_nutrition
from app.services.nutrition_lookup import answer_nutrition_query
from app.services.validator import validate_meal

MAX_RETRY = 2


def _build_giveup_message(conditions, meal_plan, validation_result) -> str:
    """재시도를 다 쓰고도 기준을 못 맞췄을 때의 정직한 안내.

    이상한(FAIL) 식단을 그대로 보여주지 않고, 왜 어려운지 + 어떻게 완화할지 알려준다.
    (준우 요청: "400kcal 이하로는 백반 구성이 어려워요" 식의 구체 안내)
    """
    target = getattr(conditions, "target_kcal", None)
    mtype = getattr(meal_plan, "meal_type", None) if meal_plan else None
    reason = ""
    if validation_result and validation_result.failures:
        reason = " " + validation_result.failures[0]

    if target and mtype:
        return (
            f"{target:.0f}kcal 조건으로는 {mtype} 구성이 어려웠어요.{reason} "
            f"칼로리를 조금 올리거나, 다른 형태(한그릇/백반)로 바꿔서 다시 요청해 주시겠어요?"
        )
    return (
        "조건을 모두 만족하는 식단을 찾지 못했어요."
        f"{reason} 칼로리나 제외 조건을 조금 완화해 주시겠어요?"
    )


# 추천이 아닌 분기에서 돌려줄 정해진 응답 (환각 없이 코드가 안내)
RISKY_RESPONSE = (
    "건강을 해칠 수 있는 요청은 도와드리기 어려워요. "
    "저는 균형 잡힌 한 끼를 추천하는 서비스예요. "
    "칼로리나 영양 목표를 알려주시면 건강한 식단으로 도와드릴게요."
)
OUT_OF_SCOPE_RESPONSE = (
    "저는 건강한 한 끼 식단을 추천하는 서비스예요. "
    "드시고 싶은 느낌(예: 담백한, 얼큰한)이나 칼로리 목표를 말씀해 주시면 추천해드릴게요."
)
NEED_MORE_INFO_RESPONSE = (
    "어떤 한 끼를 원하세요? "
    "예를 들어 '400kcal 이하로 담백하게', '얼큰한 국물 요리'처럼 "
    "칼로리·맛·제외할 재료를 알려주시면 딱 맞게 추천해드릴게요."
)


class GraphState(TypedDict, total=False):
    user_message: str
    profile: UserProfile
    intent: IntentType | None
    conditions: UserConditions | None
    candidates_by_role: dict[str, list[FoodItem]]
    candidates: list[FoodItem]
    meal_plan: MealPlan | None
    nutrition_total: NutritionTotal | None
    validation_result: ValidationResult | None
    retry_count: int
    final_response: str
    wanted_matched: list[FoodItem]  # 사용자가 콕 집은 음식(DB 매칭) → 조합에 강제 포함
    wanted_missing: list[str]  # 요청했으나 DB에 없는 음식명(안내용)
    pending_message: str  # 멀티턴: 되묻기 직전 사용자 메시지(다음 턴에서 병합)


# 되묻기(need_more_info)를 뒤집을 만한 '조건 신호어'. LLM이 흔들려도 코드가 보정한다.
_CONDITION_SIGNALS = (
    "kcal",
    "칼로리",
    "저염",
    "나트륨",
    "고단백",
    "단백질",
    "운동",
    "헬스",
    "담백",
    "얼큰",
    "칼칼",
    "매운",
    "가볍",
    "든든",
    "야채",
    "채소",
    "국",
    "밥",
    "반찬",
    "찌개",
    "한식",
    "한상",
    "백반",
    "한그릇",
    "면",
    "다이어트",
)


def _has_condition_signal(message: str) -> bool:
    """문장에 추천 조건 신호(맛·영양·형태·음식류·숫자)가 하나라도 있으면 True."""
    if any(c.isdigit() for c in message):
        return True
    return any(w in message for w in _CONDITION_SIGNALS)


def _flatten_candidates(candidates_by_role: dict[str, list[FoodItem]]) -> list[FoodItem]:
    return [food for foods in candidates_by_role.values() for food in foods]


def _has_candidates(candidates_by_role: dict[str, list[FoodItem]]) -> bool:
    return any(candidates_by_role.values())


def _wanted_allergy_conflict(wanted, allergies, foods, contains_excluded):
    """요청한 음식이 DB엔 있지만 그 계열 전부가 알레르기 재료를 포함하는 경우를 찾는다.

    반환: (충돌한 요청 음식들, 원인 알레르기들) 문자열 튜플 — 없으면 None.
    예) 알레르기 '된장' + 요청 '된장찌개' → DB의 된장찌개 계열이 전부 '된장' 포함 → 충돌.
    일부만 알레르기라 안전한 대안이 남으면 충돌이 아니다(그건 그대로 추천).
    """
    conflict_foods, cause_allergens = [], set()
    for term in wanted:
        key = term.replace(" ", "")
        hits = [f for f in foods if key in f.food_name.replace(" ", "")]
        if not hits:
            continue  # DB에 아예 없는 건 별도 '데이터에 없음' 안내가 처리
        safe = [f for f in hits if not contains_excluded(f, allergies)]
        if not safe:  # 이 요청 음식 계열이 전부 알레르기 재료 포함 → 충돌
            conflict_foods.append(term)
            cause_allergens.update(
                a
                for a in allergies
                if any(a in f"{f.food_name} {f.ingredients or ''}" for f in hits)
            )
    if conflict_foods:
        return ", ".join(conflict_foods), ", ".join(sorted(cause_allergens))
    return None


def create_graph(
    extractor: Callable[[str], UserConditions],
    classifier: Callable[[str], IntentType] = classify_intent_stub,
    checkpointer=None,
):
    """StateGraph를 생성한다. extractor/classifier는 stub/Solar를 호출부에서 주입한다.

    checkpointer를 주면 멀티턴(되묻기→이어받기)을 지원한다(thread_id별 State 저장).
    없으면 기존처럼 매 호출이 독립적인 무상태 실행이다.
    """

    def route_node(state: GraphState) -> GraphState:
        updates: GraphState = {}
        message = state["user_message"]

        # 멀티턴 병합: 직전 턴이 되묻기(need_more_info)였다면 pending_message가 남아 있다.
        # 이번 답변을 이전 메시지와 합쳐 하나의 요청으로 재구성한다.
        # (예: "뭐 먹지?" → 되묻기 → "매운 거 400kcal" → "뭐 먹지? 매운 거 400kcal")
        pending = state.get("pending_message")
        if pending:
            message = f"{pending} {message}".strip()
            updates["user_message"] = message
            updates["pending_message"] = ""  # 병합했으니 소진
            print(f"[multiturn] 이전 되묻기와 병합 → '{message}'")
            # 되묻기에 대한 답변이므로 본질적으로 '추천 요청'이다.
            # 병합 결과에 조건 신호(맛·칼로리·형태 등)가 있으면 분류를 건너뛰고 추천으로 진행한다.
            # (이전 되묻기 문장의 물음표·단어가 분류를 흔드는 것을 방지)
            if _has_condition_signal(message):
                print(f"[intent] '{message}' → meal_recommend (멀티턴 이어받기)")
                updates["intent"] = "meal_recommend"
                return updates

        intent = classifier(message)
        # 코드 안전망: LLM이 need_more_info로 흔들려도, 문장에 실제 조건 신호가 있으면
        # 되묻지 말고 추천으로 진행한다(예: "얼큰한 거", "가볍게 먹을 거").
        # intent 자체를 여기서 바로잡아, 최종 state.intent가 실제 진행 경로와 일치하게 한다
        # (라우팅만 바꾸고 라벨을 need_more_info로 남기면 관찰·평가 시 경로와 어긋난다).
        if intent == "need_more_info" and _has_condition_signal(message):
            print(f"[intent] '{message}' → meal_recommend (조건 신호 감지, 되묻기 생략)")
            intent = "meal_recommend"
        else:
            # 어떤 분기로 갔는지 서버 로그로 확인 (디버깅·시연용)
            print(f"[intent] '{message}' → {intent}")
        updates["intent"] = intent
        return updates

    def nutrition_query_node(state: GraphState) -> GraphState:
        # 수치는 코드가 DB에서 조회 (LLM이 숫자를 지어내지 않음)
        return {"final_response": answer_nutrition_query(state["user_message"])}

    def risky_node(state: GraphState) -> GraphState:
        return {"final_response": RISKY_RESPONSE}

    def out_of_scope_node(state: GraphState) -> GraphState:
        return {"final_response": OUT_OF_SCOPE_RESPONSE}

    def need_more_info_node(state: GraphState) -> GraphState:
        # 멀티턴: 이번 메시지를 저장해 두면, 다음 턴에서 사용자의 답변과 병합해 이어간다.
        # (checkpointer가 켜져 있을 때만 유효. 없으면 그냥 되묻기 문구만 나간다.)
        return {
            "final_response": NEED_MORE_INFO_RESPONSE,
            "pending_message": state["user_message"],
        }

    def extract_node(state: GraphState) -> GraphState:
        conditions = extractor(state["user_message"])
        print(
            f"[conditions] kcal={conditions.target_kcal}({conditions.kcal_mode}) "
            f"선호={conditions.preferences} 제외={conditions.exclude_foods} "
            f"형태={conditions.meal_style}"
        )
        return {"conditions": conditions}

    def retrieve_node(state: GraphState) -> GraphState:
        conditions = state["conditions"]
        profile = state.get("profile") or UserProfile()
        validation_result = state.get("validation_result")
        relax = (
            validation_result is not None
            and validation_result.cause == "retrieve"
            and state.get("retry_count", 0) > 0
        )

        candidates_by_role = retrieve_foods(conditions, profile, relax=relax)
        updates: GraphState = {
            "candidates_by_role": candidates_by_role,
            "candidates": _flatten_candidates(candidates_by_role),
        }

        # 특정 음식 요청(wanted_foods) 처리: 이름으로 DB 매칭.
        wanted = list(conditions.wanted_foods or [])
        if wanted:
            from app.services.food_retriever import (
                contains_excluded,
                load_foods,
                match_wanted_foods,
            )

            all_foods = load_foods()
            allergies = [a for a in (profile.allergies or []) if a]

            # 안전 우선: 요청한 음식 자체에 알레르기 재료가 들어있으면(예: '된장' 알레르기 +
            # '된장찌개' 요청) 조용히 거르지 말고 그 충돌을 분명히 알린다.
            if allergies:
                conflict = _wanted_allergy_conflict(wanted, allergies, all_foods, contains_excluded)
                if conflict:
                    foods_txt, alg_txt = conflict
                    updates["final_response"] = (
                        f"요청하신 '{foods_txt}'에는 알레르기·못 드시는 재료 '{alg_txt}'이(가) "
                        "들어있어 추천에서 제외했어요. 다른 음식으로 요청해 주시겠어요?"
                    )
                    return updates

            # 제외 음식(exclude_foods)·알레르기를 넘겨, "된장찌개 원하지만 부대된장찌개는 말고"
            # 같은 요청에서 제외/알레르기 대상이 강제 포함되지 않게 한다.
            matched, missing = match_wanted_foods(
                wanted,
                all_foods,
                excluded=list(conditions.exclude_foods or []) + allergies,
            )
            # 요청한 음식이 하나도 DB에 없으면 지어내지 않고 솔직히 안내
            if not matched:
                updates["final_response"] = (
                    f"'{', '.join(missing)}'은(는) 저희 데이터에 없어요. "
                    "다른 음식이나 '담백한/얼큰한' 같은 조건으로 요청해 주시겠어요?"
                )
                return updates
            # 매칭된 음식은 조합에 반드시 포함되도록 상태에 실어 compose로 전달
            updates["wanted_matched"] = list(matched.values())
            if missing:
                updates["wanted_missing"] = missing

        if not _has_candidates(candidates_by_role):
            updates["final_response"] = "조건에 맞는 음식을 찾지 못했습니다. 조건을 완화해 주세요."
        return updates

    def compose_node(state: GraphState) -> GraphState:
        meal_plan = compose_meal(
            state.get("candidates_by_role", {}),
            state["conditions"],
            seed=state.get("retry_count", 0),
            must_include=state.get("wanted_matched") or None,
        )
        names = " + ".join(f.food_name for f in meal_plan.items)
        print(f"[compose] {meal_plan.meal_type} 조합: {names}")
        return {"meal_plan": meal_plan}

    def calculate_node(state: GraphState) -> GraphState:
        nutrition = calculate_nutrition(state["meal_plan"])
        print(
            f"[calculate] 합산: {nutrition.total_kcal:.0f}kcal / "
            f"탄{nutrition.total_carbohydrate:.0f}g 단{nutrition.total_protein:.0f}g "
            f"지{nutrition.total_fat:.0f}g / 나트륨 {nutrition.total_sodium:.0f}mg"
        )
        return {"nutrition_total": nutrition}

    def validate_node(state: GraphState) -> GraphState:
        validation_result = validate_meal(
            state["meal_plan"],
            state["nutrition_total"],
            state["conditions"],
            state.get("profile") or UserProfile(),
        )
        updates: GraphState = {"validation_result": validation_result}

        reasons = validation_result.warnings + validation_result.failures
        detail = f" — {'; '.join(reasons)}" if reasons else ""
        cause = f" (원인={validation_result.cause})" if validation_result.cause else ""
        print(f"[validate] {validation_result.status}{cause}{detail}")

        if validation_result.status in ("PASS", "PASS_WITH_WARNING"):
            from app.agents.meal_agent import build_final_response

            final_state = AgentState.model_validate({**state, **updates})
            updates["final_response"] = build_final_response(final_state)
            return updates

        retry_count = state.get("retry_count", 0)
        if retry_count < MAX_RETRY:
            print(f"[retry] {retry_count + 1}/{MAX_RETRY} → {validation_result.cause}로 되돌아감")
            updates["retry_count"] = retry_count + 1
            return updates
        print("[retry] 소진 → 정직한 안내문 반환")

        updates["final_response"] = _build_giveup_message(
            state["conditions"], state.get("meal_plan"), validation_result
        )
        return updates

    def route_after_retrieve(state: GraphState) -> Literal["compose", "end"]:
        # wanted_foods가 전부 DB에 없어 안내문이 이미 세팅된 경우 즉시 종료
        if state.get("final_response"):
            return "end"
        return "compose" if _has_candidates(state.get("candidates_by_role", {})) else "end"

    def route_after_validate(state: GraphState) -> Literal["retrieve", "compose", "end"]:
        validation_result = state.get("validation_result")
        if validation_result is None or validation_result.status in ("PASS", "PASS_WITH_WARNING"):
            return "end"
        if state.get("final_response"):
            return "end"
        return "retrieve" if validation_result.cause == "retrieve" else "compose"

    def route_by_intent(
        state: GraphState,
    ) -> Literal["extract", "nutrition_query", "risky", "out_of_scope", "need_more_info"]:
        # meal_recommend만 추천 파이프라인(extract~)으로, 나머지는 각 응답 노드로 종료
        intent = state.get("intent")
        if intent == "meal_recommend":
            return "extract"
        # 코드 안전망: LLM이 need_more_info로 흔들려도, 문장에 실제 조건 신호가 있으면
        # 되묻지 말고 추천으로 진행한다(예: "국이랑 밥 있는 한식", "얼큰한 거").
        if intent == "need_more_info" and _has_condition_signal(state.get("user_message", "")):
            return "extract"
        return intent or "extract"

    builder = StateGraph(GraphState)
    builder.add_node("route", route_node)
    builder.add_node("nutrition_query", nutrition_query_node)
    builder.add_node("risky", risky_node)
    builder.add_node("out_of_scope", out_of_scope_node)
    builder.add_node("need_more_info", need_more_info_node)
    builder.add_node("extract", extract_node)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("compose", compose_node)
    builder.add_node("calculate", calculate_node)
    builder.add_node("validate", validate_node)

    builder.add_edge(START, "route")
    builder.add_conditional_edges(
        "route",
        route_by_intent,
        {
            "extract": "extract",
            "nutrition_query": "nutrition_query",
            "risky": "risky",
            "out_of_scope": "out_of_scope",
            "need_more_info": "need_more_info",
        },
    )
    # 추천이 아닌 분기는 응답만 세팅하고 즉시 종료
    builder.add_edge("nutrition_query", END)
    builder.add_edge("risky", END)
    builder.add_edge("out_of_scope", END)
    builder.add_edge("need_more_info", END)
    builder.add_edge("extract", "retrieve")
    builder.add_conditional_edges(
        "retrieve",
        route_after_retrieve,
        {"compose": "compose", "end": END},
    )
    builder.add_edge("compose", "calculate")
    builder.add_edge("calculate", "validate")
    builder.add_conditional_edges(
        "validate",
        route_after_validate,
        {"retrieve": "retrieve", "compose": "compose", "end": END},
    )
    return builder.compile(checkpointer=checkpointer)


# 멀티턴 State 저장소(프로세스 전역). thread_id별 대화 맥락을 세션 동안 유지한다.
# MVP라 인메모리 — 서버 재시작 시 초기화(기획서 '세션 간 장기기억은 비목표'와 일치).
_CHECKPOINTER = None


def _get_checkpointer():
    """MemorySaver 싱글톤. 한 번만 만들어 재사용해야 thread별 State가 유지된다."""
    global _CHECKPOINTER
    if _CHECKPOINTER is None:
        from langgraph.checkpoint.memory import MemorySaver

        _CHECKPOINTER = MemorySaver()
    return _CHECKPOINTER


def run_agent(
    user_message: str,
    profile: UserProfile = None,
    extractor: Callable[[str], UserConditions] = extract_conditions_stub,
    classifier: Callable[[str], IntentType] = classify_intent_stub,
    thread_id: str | None = None,
) -> AgentState:
    """공개 진입점. 요청 분류(intent) → 분기 → (추천이면) 파이프라인. 반환형은 기존과 동일.

    thread_id를 주면 멀티턴(되묻기→이어받기)을 지원한다. 없으면 기존처럼 무상태 실행.
    """
    initial_state = AgentState(user_message=user_message, profile=profile or UserProfile())

    if thread_id:
        graph = create_graph(extractor, classifier, checkpointer=_get_checkpointer())
        config = {"configurable": {"thread_id": thread_id}}
        result = graph.invoke(initial_state.__dict__.copy(), config=config)
    else:
        graph = create_graph(extractor, classifier)
        result = graph.invoke(initial_state.__dict__.copy())
    return AgentState.model_validate(result)


# 그래프 노드명 → 사용자에게 보여줄 '지금 무슨 단계인가' 문구.
# LangGraph .stream()이 노드가 끝날 때마다 노드명을 흘려주므로, 이걸로 실시간 진행표시를 만든다.
NODE_PROGRESS = {
    "route": "요청을 이해하고 있어요…",
    "extract": "건강 조건을 분석하고 있어요…",
    "retrieve": "어울리는 음식을 찾고 있어요…",
    "compose": "한 끼 조합을 구성하고 있어요…",
    "calculate": "영양 성분을 계산하고 있어요…",
    "validate": "건강 기준으로 검증하고 있어요…",
}


def stream_agent(
    user_message: str,
    profile: UserProfile = None,
    extractor: Callable[[str], UserConditions] = extract_conditions_stub,
    classifier: Callable[[str], IntentType] = classify_intent_stub,
    thread_id: str | None = None,
) -> Iterator[tuple[str, object]]:
    """run_agent의 스트리밍 버전. 노드가 끝날 때마다 진행 상황을 흘려보낸다.

    yield 형태:
      ("progress", "건강 조건을 분석하고 있어요…")  # 사용자 표시용 단계 문구
      ("result", AgentState)                        # 마지막에 최종 상태 1회

    LangGraph .stream()이 각 노드 실행 후 {노드명: state_update}를 준다. 노드명을
    NODE_PROGRESS로 문구화해 진행을 알리고, 업데이트를 누적해 최종 AgentState를 만든다.
    """
    initial_state = AgentState(user_message=user_message, profile=profile or UserProfile())

    if thread_id:
        graph = create_graph(extractor, classifier, checkpointer=_get_checkpointer())
        config = {"configurable": {"thread_id": thread_id}}
        stream = graph.stream(initial_state.__dict__.copy(), config=config)
    else:
        graph = create_graph(extractor, classifier)
        stream = graph.stream(initial_state.__dict__.copy())

    # .stream()은 상태 '델타'만 주므로, 누적해서 최종 전체 상태를 만든다.
    accumulated: dict = initial_state.__dict__.copy()
    last_node: str | None = None
    for chunk in stream:
        for node_name, state_update in chunk.items():
            last_node = node_name
            if isinstance(state_update, dict):
                accumulated.update(state_update)
            phrase = NODE_PROGRESS.get(node_name)
            if phrase:
                yield ("progress", phrase)
    # 재시도 루프(validate→compose)로 같은 노드가 여러 번 진행문구를 내도 프론트는
    # 마지막 것만 보이면 되므로 문제 없다. 마지막에 최종 상태를 한 번 넘긴다.
    _ = last_node
    yield ("result", AgentState.model_validate(accumulated))
