"""
핵심 시나리오 데모 — 흐름이 끝까지 도는지 확인.

RecommendationAgent 기본값은 실제 Upstage Solar API이므로, 프로젝트 루트에
UPSTAGE_API_KEY가 설정된 .env가 있어야 동작한다 (mock으로 실행하려면
RecommendationAgent(llm=MockLLM())로 직접 교체할 것).

시나리오 1 (메인): "야근이 잦고 차가 없어서 지하철이 중요해. 밤에 안전한 동네였으면 좋겠어."
  → 이동·안전 가중치 높게 파싱 → 추천 → 근거 설명

추가 시나리오로 필수조건(대형병원), 되묻기, 임의 업종(버거·헬스장) 분기도 함께 확인한다.
"""
from __future__ import annotations

from app.agent.loop import RecommendationAgent


def show(title: str, user_text: str) -> None:
    print("=" * 70)
    print(f"[시나리오] {title}")
    print(f"[입력] {user_text}")
    print("-" * 70)
    agent = RecommendationAgent()
    res = agent.run(user_text)
    print(f"[결과 유형] {res.kind}")
    print(f"[응답]\n{res.message}")
    print("\n[ReAct trace]")
    for line in res.trace:
        print("  " + line)
    print()


if __name__ == "__main__":
    show(
        "메인 — 이동·안전 중시",
        "야근이 잦고 차가 없어서 지하철이 중요해. 밤에 안전한 동네였으면 좋겠어.",
    )
    show(
        "필수조건 — 대형병원",
        "편의점이랑 마트가 충분하고 대형병원이 꼭 있어야 해.",
    )
    show(
        "되묻기 — 성향 모호",
        "그냥 살기 좋은 데 아무데나 추천해줘.",
    )
    show(
        "임의 업종 — 버거·헬스장",
        "헬스장이랑 버거집이 가까이 있었으면 좋겠고, 공원도 많았으면 해.",
    )
