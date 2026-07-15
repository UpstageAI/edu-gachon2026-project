from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel

from app.domain.models import SubstituteCandidate


class VoiceQueryState(BaseModel):
    messages: Annotated[list[AnyMessage], add_messages] = []
    recipe_id: str
    allergen_ids: list[str] = []
    allergies: list[str] = []
    recipe_name: str | None = None
    recipe_category: str | None = None
    question: str = ""
    current_step_text: str | None = None  # FE가 지금 보여주고 있는 스텝 원문(참고용 힌트)

    substitutes: list[SubstituteCandidate] = []
    turns: int = 0

    guardrail_blocked: bool = False
    final_answer: str | None = None
