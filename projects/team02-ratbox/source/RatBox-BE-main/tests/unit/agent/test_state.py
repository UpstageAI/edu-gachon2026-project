from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from app.agent.state import AgentState
from app.domain.models import RecipeCandidate


def test_state_graph_accumulates_messages_and_overwrites_plain_fields():
    def node_a(state):
        return {
            "candidate_recipes": [RecipeCandidate(id="1", name="계란밥")],
            "messages": [HumanMessage(content="첫 턴")],
        }

    def node_b(state):
        return {
            "candidate_recipes": [RecipeCandidate(id="2", name="김치볶음밥")],
            "messages": [HumanMessage(content="두번째")],
        }

    graph = StateGraph(AgentState)
    graph.add_node("a", node_a)
    graph.add_node("b", node_b)
    graph.add_edge(START, "a")
    graph.add_edge("a", "b")
    graph.add_edge("b", END)
    compiled = graph.compile()

    result = compiled.invoke(AgentState())

    assert len(result["messages"]) == 2
    assert [r.id for r in result["candidate_recipes"]] == ["2"]
