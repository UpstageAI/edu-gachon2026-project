from langchain_core.messages import HumanMessage
from state import create_initial_state


def test_create_initial_state_defaults():
    state = create_initial_state(session_id="sess-1")

    assert state["session_id"] == "sess-1"
    assert state["inquiry_id"] is None
    assert state["messages"] == []
    assert state["masked_text"] is None
    assert state["intent"] is None
    assert state["retrieved_docs"] == []
    assert state["ai_answer"] is None
    assert state["final_answer"] is None
    assert state["status"] == "문의 접수"
    assert state["reviewer_type"] is None
    assert isinstance(state["pipeline_started_at"], float)


def test_create_initial_state_with_optional_fields():
    messages = [HumanMessage(content="환불하고 싶어요")]

    state = create_initial_state(
        session_id="sess-2",
        inquiry_id="inq-123",
        messages=messages,
    )

    assert state["inquiry_id"] == "inq-123"
    assert state["messages"] == messages
