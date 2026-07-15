"""P0 진단: 가드레일 under-fire 7개 케이스의 실제 top_score/검색문서 관찰.

범위밖 질문(answerable=False)인데 guardrail=False로 답해버린 케이스가 대상.
raw json에는 answerable 케이스만 top_score가 남으므로, 여기서 직접 rag_node에 태워
실제 리랭커 점수와 검색 문서를 찍는다. → 임계값 상향(0.45/0.50)이 구제하는지 판정.

사용법:  python -m eval.diag_guardrail
"""

import asyncio
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/gachon_ai")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import HumanMessage  # noqa: E402

from app import config  # noqa: E402
from app.graph.nodes import classify_categories, rag_node, router_node  # noqa: E402

# under-fire 7개 (S24, S41~S48 계열) — 범위밖 질문
CASES = [
    ("S24", "IT 동아리 뭐뭐 있어?"),
    ("S41", "재수강 규정 알려줘"),
    ("S42", "계절학기 등록금 얼마야?"),
    ("S43", "전과하려면 학점 얼마나 필요해?"),
    ("S44", "이번 학기 등록금 얼마야?"),
    ("S46", "기숙사 한 학기 비용 얼마야?"),
    ("S48", "학교 셔틀버스 시간표 알려줘"),
]


def _base_state(q):
    return {
        "messages": [HumanMessage(content=q)],
        "session_id": "diag",
        "intent": None,
        "query": None,
        "applied_curriculum_year": None,
        "category_l1": None,
        "retrieved_docs": [],
        "tool_name": None,
        "tool_args": None,
        "tool_result": None,
        "guardrail": False,
        "contact": None,
        "admission_year": None,
        "year_prompted": False,
        "pending_action": None,
    }


async def main():
    thresh = config.GUARDRAIL_MIN_SCORE
    print(f"현재 GUARDRAIL_MIN_SCORE = {thresh}\n")
    print(f"{'ID':<5} {'top_score':>9} {'guardrail':>9}  rule_cats / 최상위 문서")
    print("-" * 90)

    tops = []
    for sid, q in CASES:
        state = _base_state(q)
        state.update(await router_node(state))
        q_eff = state.get("query") or q
        rule_cats = classify_categories(q_eff)
        state.update(await rag_node(state))
        docs = state.get("retrieved_docs") or []
        guardrail = state.get("guardrail")
        top = docs[0]["score"] if docs else None
        tops.append((sid, top, guardrail))
        top_s = f"{top:.3f}" if top is not None else "None"
        src = ""
        if docs:
            d0 = docs[0]
            meta = d0.get("metadata", {}) if isinstance(d0, dict) else {}
            src = f"{meta.get('category', '?')}/{meta.get('source', meta.get('title', '?'))}"
        print(f"{sid:<5} {top_s:>9} {str(guardrail):>9}  {rule_cats} | {src}")
        print(f"       Q: {q}")

    print("\n=== 임계값 상향 시 구제 판정 (top_score < new_thresh 여야 가드레일 발동=정답) ===")
    scored = [(s, t) for s, t, g in tops if t is not None]
    none_cnt = sum(1 for s, t, g in tops if t is None)
    if none_cnt:
        print(
            f"  주의: top_score=None {none_cnt}건 — 검색문서 0개(=이미 guardrail이 발동해야 정상). 별도 확인."
        )
    for nt in [0.42, 0.45, 0.48, 0.50, 0.55]:
        fixed = sum(1 for s, t in scored if t < nt)
        print(f"  thresh={nt}: 점수보유 {len(scored)}건 중 {fixed}개 구제")


if __name__ == "__main__":
    asyncio.run(main())
