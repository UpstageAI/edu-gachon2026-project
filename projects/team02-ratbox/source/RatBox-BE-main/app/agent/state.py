from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel

from app.agent.tools.schemas import ClassifyMissingOutput
from app.domain.models import RecipeCandidate, RecipeDetail, SubstituteCandidate


class AgentState(BaseModel):
    messages: Annotated[list[AnyMessage], add_messages] = []
    ingredient_ids: list[str] = []
    allergen_ids: list[str] = []
    recipe_id: str | None = None  # None=후보 추천 단계, 값 있으면 선택 후 상세 단계

    selected_ingredients: list[str] = []  # resolve_inputs가 ingredient_ids로부터 채움
    allergies: list[str] = []  # resolve_inputs가 allergen_ids로부터 채움

    candidate_recipes: list[RecipeCandidate] = []
    owned_ingredients: list[str] = []
    missing_ingredients: list[str] = []
    missing_classification: ClassifyMissingOutput | None = None
    substitutes: list[SubstituteCandidate] = []
    recipe_detail: RecipeDetail | None = None
    cooking_steps: list[str] = []

    react_turns: int = 0
    sql_failure_count: int = 0

    # search_recipes/verify_relevance 검색-검증 루프 관련 상태
    min_match: int = 2  # 후보로 인정할 최소 재료 매칭 개수 (broaden_search가 낮춤)
    search_limit: int = 20  # search_recipes가 가져올 후보 상한 (broaden_search가 늘림)
    retry_count: int = 0
    relevance_passed: bool = False
    relevance_reason: str | None = None
    low_confidence: bool = False

    guardrail_blocked: bool = False
    guardrail_reason: str | None = None
    final_message: str | None = None
