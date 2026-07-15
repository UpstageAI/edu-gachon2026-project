from app.agent.services import substitute_service
from app.agent.tools.schemas import FindSubstitutesOutput
from app.domain.models import SubstituteCandidate


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


def test_find_returns_llm_structured_output(monkeypatch):
    expected = FindSubstitutesOutput(
        substitutes=[
            SubstituteCandidate(ingredient_name="간장", substitute_name="소금", note="비슷한 짠맛")
        ],
        reason="간장이 없으면 소금으로 짠맛을 대신할 수 있다",
    )
    monkeypatch.setattr(substitute_service, "get_llm", lambda: _FakeLLM(expected))

    result = substitute_service.find("간장", "김치볶음밥", "볶음 요리")

    assert result == expected


def test_find_includes_exclude_ingredients_in_prompt(monkeypatch):
    expected = FindSubstitutesOutput(substitutes=[], reason="대체 불가")
    fake_llm = _FakeLLM(expected)
    monkeypatch.setattr(substitute_service, "get_llm", lambda: fake_llm)

    substitute_service.find(
        "양파", "토마토야채스프", "국/탕", exclude_ingredients=["마늘", "샐러리"]
    )

    assert "마늘" in fake_llm.last_structured.last_prompt
    assert "샐러리" in fake_llm.last_structured.last_prompt


def test_find_includes_owned_ingredients_in_prompt(monkeypatch):
    """사용자가 이미 가진 재료를 프롬프트에 넘겨야 LLM이 그걸 우선 추천할 수 있다."""
    expected = FindSubstitutesOutput(substitutes=[], reason="대체 불가")
    fake_llm = _FakeLLM(expected)
    monkeypatch.setattr(substitute_service, "get_llm", lambda: fake_llm)

    substitute_service.find(
        "멸치육수", "된장찌개", "국/탕", owned_ingredients=["물", "된장"]
    )

    assert "물" in fake_llm.last_structured.last_prompt
    assert "된장" in fake_llm.last_structured.last_prompt
