"""stateless LangGraph StateGraph 조립.

Checkpointer가 없으므로 요청마다 새 AgentState로 그래프를 1회 invoke한다.
recipe_id가 없으면 Phase A(후보 3개 추천), 있으면 Phase B(선택된 레시피 상세)로 분기한다.

Phase A 후보 검색은 LLM이 매번 SQL을 생성하던 방식(react_agent/tool_node) 대신,
재료 매칭 개수 기준의 결정론적 검색(search_recipes)을 쓴다. 검색 자체는 항상 같은
입력에 같은 결과가 나와야 하는 로직이라 LLM에 맡기지 않고, 결과가 실제로 관련성이
높은지 판단(verify_relevance)만 LLM이 맡는다. 검증에 실패하면 조건을 완화해 재시도하고
(broaden_search), 재시도를 다 써도 후보가 있으면 확신이 낮다는 단서를 달아 반환하고
(best_effort_response), 후보가 정말 하나도 없을 때만 재료 추가를 요청한다
(ask_clarification) — 무조건 되묻기만 하는 걸 피하기 위함.
"""

from functools import lru_cache

from langfuse import observe
from langgraph.graph import END, START, StateGraph

from app.agent.nodes.ask_clarification import ask_clarification
from app.agent.nodes.best_effort_response import best_effort_response
from app.agent.nodes.broaden_search import broaden_search
from app.agent.nodes.classify_and_substitute import classify_and_substitute
from app.agent.nodes.input_guardrail import input_guardrail
from app.agent.nodes.output_guardrail import output_guardrail
from app.agent.nodes.rank_candidates import rank_candidates
from app.agent.nodes.resolve_inputs import resolve_inputs
from app.agent.nodes.respond import respond
from app.agent.nodes.search_recipes import search_recipes
from app.agent.nodes.validate import validate
from app.agent.nodes.verify_relevance import verify_relevance
from app.agent.state import AgentState

MAX_SEARCH_RETRIES = 2


def _route_after_input_guardrail(state: AgentState) -> str:
    if state.guardrail_blocked:
        return "respond"
    return "search_recipes" if state.recipe_id is None else "classify_and_substitute"


def _route_after_verify_relevance(state: AgentState) -> str:
    if state.relevance_passed:
        return "respond"
    if state.retry_count < MAX_SEARCH_RETRIES:
        return "broaden_search"
    return "best_effort_response" if state.candidate_recipes else "ask_clarification"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("resolve_inputs", resolve_inputs)
    graph.add_node("input_guardrail", input_guardrail)
    graph.add_node("search_recipes", search_recipes)
    graph.add_node("rank_candidates", rank_candidates)
    graph.add_node("verify_relevance", verify_relevance)
    graph.add_node("broaden_search", broaden_search)
    graph.add_node("best_effort_response", best_effort_response)
    graph.add_node("ask_clarification", ask_clarification)
    graph.add_node("classify_and_substitute", classify_and_substitute)
    graph.add_node("validate", validate)
    graph.add_node("output_guardrail", output_guardrail)
    graph.add_node("respond", respond)

    graph.add_edge(START, "resolve_inputs")
    graph.add_edge("resolve_inputs", "input_guardrail")
    graph.add_conditional_edges(
        "input_guardrail",
        _route_after_input_guardrail,
        {
            "respond": "respond",
            "search_recipes": "search_recipes",
            "classify_and_substitute": "classify_and_substitute",
        },
    )
    graph.add_edge("search_recipes", "rank_candidates")
    graph.add_edge("rank_candidates", "verify_relevance")
    graph.add_conditional_edges(
        "verify_relevance",
        _route_after_verify_relevance,
        {
            "respond": "respond",
            "broaden_search": "broaden_search",
            "best_effort_response": "best_effort_response",
            "ask_clarification": "ask_clarification",
        },
    )
    graph.add_edge("broaden_search", "search_recipes")
    graph.add_edge("best_effort_response", "respond")
    graph.add_edge("ask_clarification", "respond")
    graph.add_edge("classify_and_substitute", "validate")
    graph.add_edge("validate", "output_guardrail")
    graph.add_edge("output_guardrail", "respond")
    graph.add_edge("respond", END)

    return graph.compile()


@lru_cache
def get_graph():
    return build_graph()


@observe(name="recommend_graph")
def run_agent(
    ingredient_ids: list[str], allergen_ids: list[str], recipe_id: str | None
) -> AgentState:
    initial_state = AgentState(
        ingredient_ids=ingredient_ids, allergen_ids=allergen_ids, recipe_id=recipe_id
    )
    result = get_graph().invoke(initial_state, config={"recursion_limit": 25})
    return AgentState(**result)


def stream_agent(ingredient_ids: list[str], allergen_ids: list[str], recipe_id: str | None):
    """노드가 끝날 때마다 {node_name: 변경분} 을 흘려보내는 동기 제너레이터.

    SSE 라우트가 이걸 스레드풀에서 한 스텝씩 당겨가며 진행상황 이벤트로 변환한다.
    """
    initial_state = AgentState(
        ingredient_ids=ingredient_ids, allergen_ids=allergen_ids, recipe_id=recipe_id
    )
    yield from get_graph().stream(
        initial_state, config={"recursion_limit": 25}, stream_mode="updates"
    )
