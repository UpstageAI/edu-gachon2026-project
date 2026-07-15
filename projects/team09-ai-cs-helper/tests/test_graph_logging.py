from langchain_core.messages import HumanMessage

from app.graph import nodes
from app.graph.state import create_initial_state


def test_review_node_receives_retrieved_regulations(monkeypatch):
    captured = {}
    state = create_initial_state("session", messages=[HumanMessage(content="환불 문의")])
    state.update(
        {
            "inquiry_id": "inq-1",
            "masked_text": "환불 문의",
            "ai_answer": "환불 규정에 따른 답변",
            "retrieved_docs": [
                {"content": "제10조 환불 규정", "metadata": {}, "score": 0.9},
                {"content": "제11조 수수료 규정", "metadata": {}, "score": 0.8},
            ],
        }
    )

    def fake_ask_with_usage(prompt):
        captured["prompt"] = prompt
        return nodes.llm.LLMResult(
            content='{"answer_review":"pass","review_feedback":null}',
            model="test-model",
            token_usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        )

    logs = []
    monkeypatch.setattr(nodes.llm, "ask_with_usage", fake_ask_with_usage)
    monkeypatch.setattr(
        nodes,
        "append_inquiry_log",
        lambda *args, **kwargs: logs.append(kwargs) or True,
    )

    result = nodes.review_node(state)

    assert result["answer_review"] == "pass"
    assert "<retrieved_documents>" in captured["prompt"]
    assert "제10조 환불 규정" in captured["prompt"]
    assert "제11조 수수료 규정" in captured["prompt"]
    assert logs[0]["data"]["model"] == "test-model"
    assert logs[0]["data"]["token_usage"]["total_tokens"] == 120
