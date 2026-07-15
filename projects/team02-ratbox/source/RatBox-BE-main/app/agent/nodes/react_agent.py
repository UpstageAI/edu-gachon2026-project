"""도구 선택 ReAct 판단 노드 (Phase A: 후보 검색). generate_sql/execute_sql 중 필요한 도구를
스스로 선택해 호출하도록 LLM에 bind_tools 한다."""

from langchain_core.messages import HumanMessage, SystemMessage
from langfuse import observe

from app.agent.prompts.react_agent_prompt import REACT_AGENT_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.agent.tools.registry import ALL_TOOLS
from app.core.llm import get_llm


@observe(name="react_agent", as_type="generation")
def react_agent(state: AgentState) -> dict:
    new_messages = []
    if not state.messages:
        new_messages.extend(
            [
                SystemMessage(content=REACT_AGENT_SYSTEM_PROMPT),
                HumanMessage(content=f"보유 재료: {state.selected_ingredients}"),
            ]
        )

    conversation = [*state.messages, *new_messages]
    llm = get_llm().bind_tools(ALL_TOOLS)
    response = llm.invoke(conversation)
    new_messages.append(response)

    return {"messages": new_messages, "react_turns": state.react_turns + 1}
