from langchain_core.messages import AIMessage

from app.agent.nodes import voice_query_nodes as voice_query_nodes_module
from app.agent.voice_state import VoiceQueryState
from app.domain.models import SubstituteCandidate


def test_voice_input_guardrail_blocks_empty_question():
    state = VoiceQueryState(recipe_id="1", question="   ")

    result = voice_query_nodes_module.voice_input_guardrail(state)

    assert result["guardrail_blocked"] is True
    assert "비어있어요" in result["final_answer"]


def test_voice_input_guardrail_allows_non_empty_question():
    state = VoiceQueryState(recipe_id="1", question="계란 대신 뭐 넣어요?")

    assert voice_query_nodes_module.voice_input_guardrail(state) == {"guardrail_blocked": False}


def test_voice_resolve_inputs_fills_recipe_and_allergies(monkeypatch):
    monkeypatch.setattr(
        voice_query_nodes_module,
        "get_recipe_by_id",
        lambda recipe_id: {"name": "계란밥", "category": "한식"},
    )
    monkeypatch.setattr(
        voice_query_nodes_module, "get_allergen_names_by_ids", lambda ids: ["새우"]
    )

    result = voice_query_nodes_module.voice_resolve_inputs(
        VoiceQueryState(recipe_id="1", allergen_ids=["allergen-1"], question="q")
    )

    assert result == {
        "recipe_name": "계란밥",
        "recipe_category": "한식",
        "allergies": ["새우"],
    }


def test_voice_resolve_inputs_handles_missing_recipe(monkeypatch):
    monkeypatch.setattr(voice_query_nodes_module, "get_recipe_by_id", lambda recipe_id: None)
    monkeypatch.setattr(voice_query_nodes_module, "get_allergen_names_by_ids", lambda ids: [])

    result = voice_query_nodes_module.voice_resolve_inputs(
        VoiceQueryState(recipe_id="missing", question="q")
    )

    assert result == {"recipe_name": None, "recipe_category": None, "allergies": []}


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


def test_voice_react_agent_seeds_conversation_on_first_call(monkeypatch):
    response = AIMessage(content="", tool_calls=[])
    fake_llm = _FakeLLM(response)
    monkeypatch.setattr(voice_query_nodes_module, "get_llm", lambda: fake_llm)

    state = VoiceQueryState(recipe_id="1", question="계란 대신 뭐 넣어요?")
    result = voice_query_nodes_module.voice_react_agent(state)

    assert len(result["messages"]) == 3  # system + human + AI response
    assert result["turns"] == 1


def test_voice_react_agent_only_appends_response_on_later_calls(monkeypatch):
    response = AIMessage(content="done", tool_calls=[])
    fake_llm = _FakeLLM(response)
    monkeypatch.setattr(voice_query_nodes_module, "get_llm", lambda: fake_llm)

    state = VoiceQueryState(
        recipe_id="1",
        question="q",
        messages=[AIMessage(content="prev")],
        turns=1,
    )
    result = voice_query_nodes_module.voice_react_agent(state)

    assert len(result["messages"]) == 1
    assert result["turns"] == 2


def test_voice_validate_flags_substitute_matching_allergy():
    state = VoiceQueryState(
        recipe_id="1",
        question="q",
        allergies=["새우"],
        substitutes=[SubstituteCandidate(ingredient_name="간장", substitute_name="새우")],
    )

    result = voice_query_nodes_module.voice_validate(state)

    assert result["substitutes"][0].allergy_conflict is True


def test_voice_respond_returns_final_message_when_blocked():
    state = VoiceQueryState(
        recipe_id="1", question="q", guardrail_blocked=True, final_answer="차단됨"
    )

    assert voice_query_nodes_module.voice_respond(state) == {}


def test_voice_respond_warns_on_allergy_conflict():
    state = VoiceQueryState(
        recipe_id="1",
        question="q",
        substitutes=[
            SubstituteCandidate(
                ingredient_name="계란", substitute_name="새우", allergy_conflict=True
            )
        ],
    )

    result = voice_query_nodes_module.voice_respond(state)

    assert "알레르기 성분일 수 있어요" in result["final_answer"]


def test_voice_respond_uses_last_ai_message_when_no_conflict():
    state = VoiceQueryState(
        recipe_id="1",
        question="q",
        messages=[AIMessage(content="대신 두부를 쓰면 돼요.")],
    )

    result = voice_query_nodes_module.voice_respond(state)

    assert result["final_answer"] == "대신 두부를 쓰면 돼요."


def test_voice_respond_strips_markdown_from_ai_message():
    state = VoiceQueryState(
        recipe_id="1",
        question="q",
        messages=[AIMessage(content="**두부**를 대신 쓰면 돼요.")],
    )

    result = voice_query_nodes_module.voice_respond(state)

    assert result["final_answer"] == "두부를 대신 쓰면 돼요."
