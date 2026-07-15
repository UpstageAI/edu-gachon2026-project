from app.agent.services import steps_service
from app.agent.tools.schemas import GenerateCookingStepsOutput


class _FakeStructuredLLM:
    def __init__(self, output):
        self._output = output

    def invoke(self, prompt):
        return self._output


class _FakeLLM:
    def __init__(self, output):
        self._output = output

    def with_structured_output(self, schema):
        return _FakeStructuredLLM(self._output)


def test_generate_returns_llm_steps(monkeypatch):
    expected = GenerateCookingStepsOutput(steps=["재료를 손질한다.", "볶는다.", "그릇에 담는다."])
    monkeypatch.setattr(steps_service, "get_llm", lambda: _FakeLLM(expected))

    result = steps_service.generate(
        recipe_name="김치볶음",
        category="메인반찬",
        cooking_method="볶음",
        ingredients=["김치", "밥", "대파"],
    )

    assert result == expected
