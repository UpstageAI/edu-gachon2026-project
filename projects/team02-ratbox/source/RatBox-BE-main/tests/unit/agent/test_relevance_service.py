from app.agent.services import relevance_service
from app.agent.services.relevance_service import VerifyRelevanceOutput
from app.domain.models import RecipeCandidate


def test_verify_short_circuits_when_no_candidates():
    result = relevance_service.verify(["카레", "양파"], [])

    assert result.passed is False


def test_verify_uses_llm_when_candidates_exist(monkeypatch):
    class _FakeStructuredLLM:
        def invoke(self, prompt):
            assert "카레" in prompt
            return VerifyRelevanceOutput(passed=True, reason="적절해요")

    class _FakeLLM:
        def with_structured_output(self, schema):
            return _FakeStructuredLLM()

    monkeypatch.setattr(relevance_service, "get_llm", lambda: _FakeLLM())

    candidates = [RecipeCandidate(id="1", name="카레라이스", missing_ingredients=[])]
    result = relevance_service.verify(["카레", "양파"], candidates)

    assert result.passed is True
    assert result.reason == "적절해요"
