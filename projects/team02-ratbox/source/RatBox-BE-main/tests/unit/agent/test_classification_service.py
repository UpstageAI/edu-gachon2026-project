from app.agent.services import classification_service
from app.agent.tools.schemas import ClassifyMissingOutput


class _FakeStructuredLLM:
    def __init__(self, output):
        self._output = output
        self.last_prompt = None

    def invoke(self, prompt):
        self.last_prompt = prompt
        return self._output


class _FakeLLM:
    def __init__(self, output):
        self._output = output
        self.last_structured = None

    def with_structured_output(self, schema):
        self.last_structured = _FakeStructuredLLM(self._output)
        return self.last_structured


def test_classify_uses_recipe_ingredients_and_llm(monkeypatch):
    expected = ClassifyMissingOutput(
        required=["소고기"], optional=["대파"], reason="핵심 단백질 없음"
    )
    monkeypatch.setattr(
        classification_service,
        "get_recipe_ingredient_names",
        lambda recipe_id: [
            {"name": "소고기", "is_required": True},
            {"name": "대파", "is_required": False},
            {"name": "밥", "is_required": True},
        ],
    )
    monkeypatch.setattr(classification_service, "get_llm", lambda: _FakeLLM(expected))

    result = classification_service.classify("recipe-1", available_ingredients=["밥"])

    assert result == expected


def test_classify_does_not_leak_meaningless_is_required_flag_into_prompt(monkeypatch):
    """ingestion이 모든 재료에 is_required=True를 무조건 넣고 있어(app/ingestion/cleaning.py)
    이 값은 핵심/부재료를 구분하는 신호가 아니다. 프롬프트에 그대로 넘기면 LLM이
    "is_required=True니까 필수"라고 기계적으로 판단하는 근거로 잘못 쓰인다 - 재료 이름만
    넘겨야 한다."""
    expected = ClassifyMissingOutput(required=[], optional=["대파"], reason="향만 담당")
    monkeypatch.setattr(
        classification_service,
        "get_recipe_ingredient_names",
        lambda recipe_id: [
            {"name": "소고기", "is_required": True},
            {"name": "대파", "is_required": True},
        ],
    )
    fake_llm = _FakeLLM(expected)
    monkeypatch.setattr(classification_service, "get_llm", lambda: fake_llm)

    classification_service.classify("recipe-1", available_ingredients=["소고기"])

    assert "is_required" not in fake_llm.last_structured.last_prompt
    assert "대파" in fake_llm.last_structured.last_prompt
