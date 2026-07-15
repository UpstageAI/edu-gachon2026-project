from langchain_core.messages import AIMessage

from app.agent.nodes import react_agent as react_agent_module
from app.agent.state import AgentState


class _FakeBoundLLM:
    def __init__(self, response):
        self._response = response

    def invoke(self, conversation):
        self._last_conversation = conversation
        return self._response


class _FakeLLM:
    def __init__(self, response):
        self._response = response
        self.bound: _FakeBoundLLM | None = None

    def bind_tools(self, tools):
        self.bound = _FakeBoundLLM(self._response)
        return self.bound


def test_react_agent_seeds_conversation_on_first_call(monkeypatch):
    response = AIMessage(content="", tool_calls=[])
    fake_llm = _FakeLLM(response)
    monkeypatch.setattr(react_agent_module, "get_llm", lambda: fake_llm)

    state = AgentState(selected_ingredients=["계란", "밥"])
    result = react_agent_module.react_agent(state)

    assert len(result["messages"]) == 3  # system + human + AI response
    assert result["react_turns"] == 1


def test_react_agent_only_appends_response_on_later_calls(monkeypatch):
    response = AIMessage(content="done", tool_calls=[])
    fake_llm = _FakeLLM(response)
    monkeypatch.setattr(react_agent_module, "get_llm", lambda: fake_llm)

    state = AgentState(
        selected_ingredients=["계란"],
        messages=[AIMessage(content="prev")],
        react_turns=1,
    )
    result = react_agent_module.react_agent(state)

    assert len(result["messages"]) == 1
    assert result["react_turns"] == 2
