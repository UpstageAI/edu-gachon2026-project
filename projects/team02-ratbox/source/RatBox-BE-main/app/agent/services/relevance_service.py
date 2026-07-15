"""Phase A: 검색된 후보가 실제로 관련성 높고 재료를 잘 활용하는지 LLM으로 검증한다.

검색(search_service)은 결정론적 매칭 개수 로직이라 "카레+양파를 넣었는데 카레 계열이
하나도 안 나오는" 것 같은 의미적 이상은 잡아내지 못한다. 이 검증만 LLM이 맡는다.
"""

from langfuse import observe
from pydantic import BaseModel, Field

from app.agent.prompts.verify_relevance_prompt import build_verify_relevance_prompt
from app.core.llm import get_llm
from app.domain.models import RecipeCandidate


class VerifyRelevanceOutput(BaseModel):
    passed: bool = Field(..., description="후보들이 재료 활용도/관련성 기준을 통과하는지")
    reason: str = Field(..., description="판단 근거, 한두 문장")


@observe(name="verify_relevance", as_type="generation")
def verify(
    selected_ingredients: list[str], candidates: list[RecipeCandidate]
) -> VerifyRelevanceOutput:
    if not candidates:
        return VerifyRelevanceOutput(
            passed=False, reason="지금 재료로 만들 수 있는 레시피를 찾지 못했어요."
        )

    prompt = build_verify_relevance_prompt(selected_ingredients, candidates)
    llm = get_llm().with_structured_output(VerifyRelevanceOutput)
    return llm.invoke(prompt)
