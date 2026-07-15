"""Phase A: 검증 실패 시 검색 조건을 완화하고 재시도 횟수를 늘리는 노드. 같은
파라미터로 search_recipes를 다시 돌리면 결과가 똑같으므로, 재시도마다 조건이
달라져야 한다.

min_match와 search_limit을 매번 같이 완화하면 min_match가 바닥(MIN_MATCH_FLOOR)에
닿는 순간부터는 뒤이은 재시도가 사실상 아무 효과가 없다 - min_match는 더 못 내려가고
search_limit도 SEARCH_LIMIT_CAP에 막혀 후보 풀이 그대로인 채 LLM 판단만 다시
시도하게 된다. 그래서 두 축을 단계적으로 나눠 완화한다:
1단계(min_match > FLOOR): 재료 일치 기준(min_match)을 한 칸 낮춰 더 많은 레시피가
   후보에 들어오게 한다.
2단계(min_match == FLOOR): min_match는 더 낮출 수 없으니, 대신 search_limit을 큰 폭으로
   늘려 가중치 상위 몇 개만 보던 것을 훨씬 깊이까지 보게 한다 - rank_candidates가 더
   넓은 후보 풀에서 부족 재료가 적은 레시피를 고를 기회를 준다."""

from langfuse import observe

from app.agent.state import AgentState

MIN_MATCH_FLOOR = 1
DEEP_SEARCH_LIMIT = 60


@observe(name="broaden_search")
def broaden_search(state: AgentState) -> dict:
    if state.min_match > MIN_MATCH_FLOOR:
        return {
            "min_match": state.min_match - 1,
            "retry_count": state.retry_count + 1,
        }

    return {
        "search_limit": max(state.search_limit, DEEP_SEARCH_LIMIT),
        "retry_count": state.retry_count + 1,
    }
