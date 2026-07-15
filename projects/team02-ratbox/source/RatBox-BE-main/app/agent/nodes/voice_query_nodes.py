"""조리 중 음성 질의(B흐름) 노드 모음.

Phase A의 react_agent/tool_node ReAct 루프와 동일한 패턴으로, 대체재/생략 질문일 때만
LLM이 스스로 find_substitutes 툴을 호출하도록 하고, 그 외 질문은 일반 조리 지식으로
바로 답하게 한다.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langfuse import observe

from app.agent.services.guardrail_service import check_substitute_conflict
from app.agent.text_utils import strip_markdown
from app.agent.tools.registry import VOICE_TOOLS
from app.agent.voice_state import VoiceQueryState
from app.core.llm import get_llm
from app.data.repositories.allergen_repository import get_allergen_names_by_ids
from app.data.repositories.recipe_repository import get_recipe_by_id

VOICE_TOOLS_BY_NAME = {tool.name: tool for tool in VOICE_TOOLS}
MAX_VOICE_TURNS = 3

VOICE_SYSTEM_PROMPT = (
    "당신은 '뚜이', 영화 <라따뚜이>의 레미처럼 요리를 진심으로 사랑하는 작은 생쥐 셰프입니다. "
    "지금 사용자 옆에서 함께 요리하며 부지런히 돕고 있습니다.\n\n"
    "말투는 딱딱한 설명문이 아니라, 요리를 좋아하는 친구가 옆에서 같이 고민해주듯 "
    "다정하고 활기차게 답하세요. 사용자를 믿어주고 응원하되, 수다스럽게 늘어지지 말고 "
    "핵심은 분명하고 실용적으로 전달하세요.\n\n"
    "현재 조리 중인 레시피: {recipe_name} (분류: {recipe_category}).\n"
    "사용자의 알레르기 성분: {allergies}.\n"
    "현재 조리 단계: {current_step_text}\n"
    "(이건 참고용 맥락일 뿐입니다. 이 단계 내용을 벗어나는 질문이어도 일반 조리 지식을 "
    "활용해 자유롭게 답하세요 — 이 단계에 없는 내용이라고 답변을 거부하지 마세요.)\n\n"
    "재료 대체나 생략 가능 여부를 물으면 반드시 find_substitutes 도구로 확인한 뒤 답하세요.\n"
    "알레르기 관련 발화는 두 가지로 구분하세요:\n"
    "- 이미 알려진 알레르기 성분에 대해 묻는 것(조회)이면 위 정보로 바로 답하세요.\n"
    "- 사용자가 기존에 없던 새로운 알레르기 성분을 언급하면(예: '저 새우도 못 먹어요'), "
    "그 성분이 이 레시피에 들어갈 수 있는 재료라고 보고 find_substitutes로 대체재를 "
    "확인한 뒤 답하세요. 단, 이 정보는 이번 답변에만 반영되고 별도로 저장되지 않으니, "
    "다음에도 반영되길 원하면 알레르기 설정 화면에서 저장하라고 안내하세요.\n"
    "그 외 조리 방법/순서 질문은 알고 있는 일반 조리 지식으로 답하세요.\n"
    "알레르기 유발 재료는 절대 대체재로 추천하지 마세요.\n"
    "알레르기 정보는 실제로 관련 있을 때만 언급하세요 — 대체재 후보가 알레르기 성분과 "
    "겹치거나 충돌할 때만 그 사실을 말하세요. 지금 논의 중인 재료/대체재와 무관한 "
    "알레르기 성분을 '제외했습니다', '괜찮으실지' 같은 문구로 매번 덧붙이지 마세요.\n\n"
    "확신이 낮은 질문이어도 답변을 회피하지 말고, 아는 한도 내에서 최선의 답을 먼저 "
    "제시하세요. 정말 판단이 안 서는 경우에만 무엇이 더 필요한지 되물으세요.\n\n"
    "답변 형식 규칙:\n"
    "- 한두 문단으로 나누어 답하세요. 문단 사이는 반드시 빈 줄(줄바꿈 두 번)로 구분하세요.\n"
    "- 이모티콘은 전체 답변에 최대 1개까지만, 정말 어울릴 때만 쓰세요. 남발하지 마세요.\n"
    "- 마크다운 문법(**볼드**, 백틱, #, 인용부호(>), 목록 기호(-) 등)은 절대 쓰지 마세요 "
    "— 화면에 그대로 텍스트로 표시됩니다.\n"
    "- 도구를 호출했는지, 왜 호출하지 않았는지 같은 내부 판단 과정은 절대 답변에 적지 "
    "마세요. 사용자에게 실제로 필요한 답변 내용만 쓰세요.\n"
    "- \"AI가 검토한 결과\", \"레시피 맥락에 맞게 판단하면\" 같은 자기참조적인 서두는 "
    "쓰지 마세요. 그런 설명 없이 바로 결론과 이유만 말하세요."
)


@observe(name="voice_resolve_inputs")
def voice_resolve_inputs(state: VoiceQueryState) -> dict:
    recipe = get_recipe_by_id(state.recipe_id)
    return {
        "recipe_name": recipe["name"] if recipe else None,
        "recipe_category": recipe.get("category") if recipe else None,
        "allergies": get_allergen_names_by_ids(state.allergen_ids),
    }


@observe(name="voice_input_guardrail")
def voice_input_guardrail(state: VoiceQueryState) -> dict:
    if not state.question.strip():
        return {
            "guardrail_blocked": True,
            "final_answer": "질문 내용이 비어있어요. 다시 말씀해주세요.",
        }
    return {"guardrail_blocked": False}


@observe(name="voice_react_agent", as_type="generation")
def voice_react_agent(state: VoiceQueryState) -> dict:
    new_messages = []
    if not state.messages:
        new_messages.extend(
            [
                SystemMessage(
                    content=VOICE_SYSTEM_PROMPT.format(
                        recipe_name=state.recipe_name or "알 수 없음",
                        recipe_category=state.recipe_category or "알 수 없음",
                        allergies=", ".join(state.allergies) or "없음",
                        current_step_text=state.current_step_text or "정보 없음",
                    )
                ),
                HumanMessage(content=state.question),
            ]
        )

    conversation = [*state.messages, *new_messages]
    llm = get_llm().bind_tools(VOICE_TOOLS)
    response = llm.invoke(conversation)
    new_messages.append(response)

    return {"messages": new_messages, "turns": state.turns + 1}


@observe(name="voice_tool_node")
def voice_tool_node(state: VoiceQueryState) -> dict:
    last_message = state.messages[-1]
    tool_messages = []
    substitutes = list(state.substitutes)

    for call in last_message.tool_calls:
        tool = VOICE_TOOLS_BY_NAME[call["name"]]
        result = tool.invoke(call["args"])
        tool_messages.append(ToolMessage(content=result.model_dump_json(), tool_call_id=call["id"]))

        if call["name"] == "find_substitutes":
            substitutes.extend(result.substitutes)

    return {"messages": tool_messages, "substitutes": substitutes}


@observe(name="voice_validate")
def voice_validate(state: VoiceQueryState) -> dict:
    flagged = [
        substitute.model_copy(
            update={
                "allergy_conflict": check_substitute_conflict(
                    substitute.substitute_name, state.allergies
                )
            }
        )
        for substitute in state.substitutes
    ]
    return {"substitutes": flagged}


@observe(name="voice_respond")
def voice_respond(state: VoiceQueryState) -> dict:
    if state.guardrail_blocked:
        return {}

    conflicts = [s for s in state.substitutes if s.allergy_conflict]
    if conflicts:
        warnings = [
            f"{strip_markdown(s.ingredient_name)} 대신 {strip_markdown(s.substitute_name)}을(를) "
            "쓸 수 있지만 알레르기 성분일 수 있어요. 다른 대체재를 찾아드릴까요?"
            for s in conflicts
        ]
        return {"final_answer": " ".join(warnings)}

    last_ai = next(
        (m for m in reversed(state.messages) if isinstance(m, AIMessage) and m.content),
        None,
    )
    answer = strip_markdown(last_ai.content) if last_ai else "답변을 생성하지 못했어요."
    return {"final_answer": answer}
