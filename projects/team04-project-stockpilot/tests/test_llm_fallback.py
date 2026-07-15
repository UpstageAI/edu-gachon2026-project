import pytest
from langchain_core.messages import AIMessage, HumanMessage

import app.core.llm as llm


class _FakeModel:
    def __init__(self, model_id: str):
        self.model_id = model_id

    async def ainvoke(self, messages):
        if self.model_id == "gpt-4o-mini":
            raise RuntimeError("insufficient quota")
        return AIMessage(
            content="solar answer",
            response_metadata={"model": self.model_id},
        )


@pytest.mark.asyncio
async def test_gpt_failure_falls_back_to_solar(monkeypatch):
    monkeypatch.setattr(llm, "_available_ids", lambda: ["solar", "gpt-4o-mini"])
    monkeypatch.setattr(llm, "_build_one", lambda model_id: _FakeModel(model_id))

    result = await llm.ainvoke_with_fallback(
        [HumanMessage(content="삼성전자 왜 떨어짐?")],
        model_id="gpt-4o-mini",
    )

    assert result.message.content == "solar answer"
    assert result.model_id == "solar"
    assert result.attempted_models == ["gpt-4o-mini", "solar"]
    assert result.fallback_used is True
