"""react_agent가 선택한 도구를 실행하는 노드.

langgraph.prebuilt.ToolNode 대신 직접 구현한 이유: execute_sql의 결과(레시피 후보,
실패 여부)를 AgentState의 candidate_recipes/sql_failure_count로 끌어올려야 하는데,
프리빌트 ToolNode는 결과를 메시지로만 남기고 커스텀 state 필드에 반영해주지 않는다.
"""

from langchain_core.messages import ToolMessage
from langfuse import observe

from app.agent.state import AgentState
from app.agent.tools.registry import ALL_TOOLS

TOOLS_BY_NAME = {tool.name: tool for tool in ALL_TOOLS}


@observe(name="tool_node")
def tool_node(state: AgentState) -> dict:
    last_message = state.messages[-1]
    tool_messages = []
    updates: dict = {}

    for call in last_message.tool_calls:
        tool = TOOLS_BY_NAME[call["name"]]
        result = tool.invoke(call["args"])
        tool_messages.append(ToolMessage(content=result.model_dump_json(), tool_call_id=call["id"]))

        if call["name"] == "execute_sql":
            updates["candidate_recipes"] = result.recipes
            if result.error:
                updates["sql_failure_count"] = state.sql_failure_count + 1

    updates["messages"] = tool_messages
    return updates
