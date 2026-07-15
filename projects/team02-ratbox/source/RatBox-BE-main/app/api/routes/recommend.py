import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.agent.graph import stream_agent
from app.agent.state import AgentState
from app.api.schemas.request import RecommendRequest
from app.api.schemas.response import (
    ClassificationSummary,
    IngredientRef,
    RecipeDetailResponse,
    RecipeSummary,
    RecommendResponse,
    SubstituteSummary,
)
from app.data.repositories.ingredient_repository import get_ingredient_categories_by_names

router = APIRouter(tags=["recommend"])

# 노드가 끝날 때마다 사용자에게 보여줄 진행상황 문구. 그래프에 없는 노드 이름이 와도
# .get()이 None을 반환할 뿐이라 그래프 변경에 최대한 관대하다.
NODE_STATUS_MESSAGES = {
    "resolve_inputs": "재료 정보를 확인하고 있어요...",
    "input_guardrail": "입력을 확인하고 있어요...",
    "search_recipes": "가진 재료로 만들 수 있는 레시피를 찾고 있어요...",
    "rank_candidates": "후보를 추려내고 있어요...",
    "verify_relevance": "찾은 레시피가 적절한지 확인하고 있어요...",
    "broaden_search": "검색 범위를 넓혀서 다시 찾고 있어요...",
    "best_effort_response": "가장 가까운 레시피를 정리하고 있어요...",
    "ask_clarification": "답변을 준비하고 있어요...",
    "classify_and_substitute": "부족한 재료를 판단하고 있어요...",
    "validate": "대체재가 알레르기와 겹치지 않는지 확인하고 있어요...",
    "output_guardrail": "결과를 최종 검증하고 있어요...",
    "respond": "답변을 정리하고 있어요...",
}

_STREAM_DONE = object()


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _to_ingredient_refs(names: list[str], categories: dict[str, str | None]) -> list[IngredientRef]:
    return [IngredientRef(name=name, category=categories.get(name)) for name in names]


def _build_response(state: AgentState) -> RecommendResponse:
    # FE가 부족/보유 재료를 카테고리별로 묶어 보여줄 수 있도록, 응답 경계에서만 카테고리를
    # 덧붙인다 - 그래프 내부 로직(매칭/분류/프롬프트)은 그대로 재료 이름 기반으로 둔다.
    all_names = (
        {name for recipe in state.candidate_recipes for name in recipe.missing_ingredients}
        | set(state.owned_ingredients)
        | set(state.missing_ingredients)
    )
    categories = get_ingredient_categories_by_names(list(all_names))

    recipes = [
        RecipeSummary(
            id=recipe.id,
            name=recipe.name,
            cooking_time=recipe.cooking_time,
            missing_ingredients=_to_ingredient_refs(recipe.missing_ingredients, categories),
        )
        for recipe in state.candidate_recipes
    ]

    detail = None
    if state.recipe_detail is not None:
        detail = RecipeDetailResponse(
            recipe_id=state.recipe_detail.id,
            name=state.recipe_detail.name,
            cooking_time=state.recipe_detail.cooking_time,
            difficulty=state.recipe_detail.difficulty,
            category=state.recipe_detail.category,
            cooking_method=state.recipe_detail.cooking_method,
            owned_ingredients=_to_ingredient_refs(state.owned_ingredients, categories),
            missing_ingredients=_to_ingredient_refs(state.missing_ingredients, categories),
            classification=(
                ClassificationSummary(**state.missing_classification.model_dump())
                if state.missing_classification
                else None
            ),
            substitutes=[SubstituteSummary(**s.model_dump()) for s in state.substitutes],
            cooking_steps=state.cooking_steps,
        )

    return RecommendResponse(recipes=recipes, detail=detail, message=state.final_message or "")


def _pull_next(iterator):
    """동기 제너레이터에서 한 스텝만 당겨온다 (스레드풀 안에서 실행됨)."""
    try:
        return next(iterator)
    except StopIteration:
        return _STREAM_DONE


async def _stream_recommend(payload: RecommendRequest) -> AsyncIterator[str]:
    iterator = stream_agent(
        ingredient_ids=payload.ingredient_ids,
        allergen_ids=payload.allergen_ids,
        recipe_id=payload.recipe_id,
    )
    # LangGraph 노드가 return한 부분 업데이트를 계속 병합해 최종 state를 재구성한다.
    # messages는 add_messages 리듀서가 따로 있어 단순 병합 대상이 아니므로 제외한다.
    accumulated: dict = {}

    try:
        while True:
            step = await run_in_threadpool(_pull_next, iterator)
            if step is _STREAM_DONE:
                break
            for node_name, update in step.items():
                accumulated.update({k: v for k, v in update.items() if k != "messages"})
                message = NODE_STATUS_MESSAGES.get(node_name)
                if message:
                    yield _sse_event("status", {"node": node_name, "message": message})
    except Exception:
        yield _sse_event(
            "error", {"message": "일시적인 오류가 발생했어요, 잠시 후 다시 시도해주세요."}
        )
        yield "event: done\ndata: {}\n\n"
        return

    response = _build_response(AgentState(**accumulated))
    yield _sse_event("final", response.model_dump())
    yield "event: done\ndata: {}\n\n"


@router.post("/recommend")
async def recommend(payload: RecommendRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream_recommend(payload),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
