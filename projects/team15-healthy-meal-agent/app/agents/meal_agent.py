"""
app/agents/meal_agent.py
실제 식단 추천 에이전트의 공개 진입점.
"""

from app.agents.graph import run_agent as run_agent
from app.schemas import AgentState


def build_final_response(state: AgentState) -> str:
    """말풍선에 담을 '대화체 한두 줄'. 상세 수치·음식·경고는 아래 카드가 보여주므로
    여기서는 반복하지 않는다(중복 제거). 카드가 못 그리는 상황에서만 최소 정보 폴백.
    """
    mp = state.meal_plan
    nt = state.nutrition_total
    vr = state.validation_result

    # 음식명·수치 나열은 카드가 보여주므로, 말풍선은 '이유 한 줄 + 총 열량 안내'만.
    intro = mp.reason.rstrip() if mp.reason else f"조건에 맞춰 {mp.meal_type} 한 끼를 구성했어요."
    lines = [intro, f"총 {nt.total_kcal:.0f}kcal예요. 아래에서 영양과 레시피를 확인해 보세요."]
    if vr.warnings:
        lines.append("⚠️ " + " ".join(vr.warnings))
    return "\n".join(lines)
