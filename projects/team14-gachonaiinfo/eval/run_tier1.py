"""Tier1 평가 harness — 결정적 KPI (응답 LLM 제외).

측정: 라우팅(intent/category) 정확도, 검색 성공률, 가드레일 정확도, 지연(router/retrieval).
멀티턴 상태(admission_year/year_prompted/pending_action)는 턴 간 이어붙인다.
응답 생성 LLM은 타지 않으므로(=response 노드 skip) 저비용으로 N회 반복 가능하다.
(router LLM은 카테고리 미매칭 질문에서만 호출됨 — 이는 라우팅의 일부라 포함.)

사용법:  python -m eval.run_tier1 [N회반복=3]
"""

import asyncio
import json
import os
import sys
import time

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/gachon_ai")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import HumanMessage  # noqa: E402

from app import config, db  # noqa: E402
from app.graph.nodes import (  # noqa: E402
    ask_admission_year_node,
    classify_categories,
    rag_node,
    reminder_node,
    router_node,
    tool_node,
)
from eval.scenarios import SCENARIOS  # noqa: E402

THRESH = config.GUARDRAIL_MIN_SCORE
RESULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def _base_state(q, sid, carry):
    return {
        "messages": [HumanMessage(content=q)],
        "session_id": sid,
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
        "admission_year": carry["admission_year"],
        "year_prompted": carry["year_prompted"],
        "pending_action": carry["pending_action"],
    }


async def _run_turn(q, sid, carry):
    """한 턴을 노드로 태우고 (지표 원자료, 갱신된 carry) 반환."""
    state = _base_state(q, sid, carry)

    t0 = time.perf_counter()
    rout = await router_node(state)
    router_ms = (time.perf_counter() - t0) * 1000
    state.update(rout)
    intent = state.get("intent")

    stage_ms = None
    docs, guardrail, contact, tool_ok, message = [], None, None, None, None
    if intent == "rag":
        t0 = time.perf_counter()
        r = await rag_node(state)
        stage_ms = (time.perf_counter() - t0) * 1000
        state.update(r)
        docs = state.get("retrieved_docs") or []
        guardrail = state.get("guardrail")
        contact = state.get("contact")
    elif intent == "tool":
        t0 = time.perf_counter()
        r = await tool_node(state)
        stage_ms = (time.perf_counter() - t0) * 1000
        state.update(r)
        tr = state.get("tool_result") or {}
        tool_ok = tr.get("success")
    elif intent == "reminder":
        state.update(await reminder_node(state))
        message = getattr(state["messages"][-1], "content", None)
    elif intent == "ask_year":
        state.update(await ask_admission_year_node(state))
        message = getattr(state["messages"][-1], "content", None)

    carry = {k: state.get(k) for k in ("admission_year", "year_prompted", "pending_action")}
    return {
        "intent": intent,
        "category_l1": state.get("category_l1"),
        "tool_name": state.get("tool_name"),
        "tool_result": state.get("tool_result"),
        "docs": docs,
        "guardrail": guardrail,
        "contact": contact,
        "tool_ok": tool_ok,
        # query = 이번 턴 라우팅에 실제 쓴 질문(학번 되묻기 답변 턴이면 복원된 원질문).
        # 카테고리 채점은 이 값으로 해야 정확하다.
        "query": state.get("query"),
        "message": message,
        "router_ms": router_ms,
        "stage_ms": stage_ms,
    }, carry


def _score(turn, out):
    """라벨과 노드 출력으로 턴별 채점."""
    q = turn["q"]
    exp_intent = turn["intent"]
    answerable = turn["answerable"]
    rec = {
        "q": q,
        "exp_intent": exp_intent,
        "got_intent": out["intent"],
        "intent_ok": out["intent"] == exp_intent,
        "answerable": answerable,
        "router_ms": round(out["router_ms"], 1),
        "stage_ms": round(out["stage_ms"], 1) if out["stage_ms"] is not None else None,
    }
    # 카테고리 분류 정확도(라벨 있을 때만; 규칙 분류 기준).
    # 학번 되묻기 답변 턴은 라우터가 원질문을 복원하므로 그 질문으로 채점한다.
    exp_cat = turn.get("category")
    if exp_cat:
        q_eff = out.get("query") or q
        rule_cats = classify_categories(q_eff)
        rec["exp_cat"] = exp_cat
        rec["rule_cats"] = rule_cats
        rec["cat_ok"] = exp_cat[0] in rule_cats
    else:
        rec["cat_ok"] = None

    # 가드레일 정확도(rag 턴): guardrail == (not answerable)
    if out["intent"] == "rag":
        rec["guardrail"] = out["guardrail"]
        rec["guardrail_ok"] = (out["guardrail"] is True) == (not answerable)
    else:
        rec["guardrail_ok"] = None

    # 검색 성공률(answerable rag): 자료로 답할 수 있다고 판단(=not guardrail)
    if out["intent"] == "rag" and answerable:
        rec["retrieval_ok"] = out["guardrail"] is False and len(out["docs"]) > 0
        rec["top_score"] = round(out["docs"][0]["score"], 3) if out["docs"] else 0.0
    else:
        rec["retrieval_ok"] = None

    # 근거 확보(expect_facts): rag는 검색 문서 content, tool은 tool_result에서 확인
    facts = turn.get("expect_facts")
    if facts:
        if out["intent"] == "rag":
            hay = " ".join(d.get("content", "") for d in out["docs"])
        elif out["intent"] == "tool":
            hay = json.dumps(out["tool_result"], ensure_ascii=False)
        elif out["intent"] in ("reminder", "ask_year"):
            # 리마인드/되묻기는 노드가 만든 결정적 메시지에 사실("예약" 등)이 담긴다.
            hay = out.get("message") or ""
        else:
            hay = ""
        # 연락처 사실(전화번호 등)은 contact dict에도 있을 수 있음
        if out["contact"]:
            hay += " " + json.dumps(out["contact"], ensure_ascii=False)
        rec["facts_hit"] = all(f in hay for f in facts)
    else:
        rec["facts_hit"] = None

    # 도구 성공
    if out["intent"] == "tool":
        rec["tool_ok"] = out["tool_ok"]
    return rec


async def run_all(n_runs):
    all_recs = []
    for run_idx in range(n_runs):
        for sc in SCENARIOS:
            sid = f"__eval__{sc['id']}_{run_idx}"
            carry = {"admission_year": None, "year_prompted": False, "pending_action": None}
            for i, turn in enumerate(sc["turns"]):
                out, carry = await _run_turn(turn["q"], sid, carry)
                rec = _score(turn, out)
                rec.update(
                    {"run": run_idx, "scenario": sc["id"], "persona": sc["persona"], "turn": i}
                )
                all_recs.append(rec)
        print(f"  run {run_idx + 1}/{n_runs} 완료")
    return all_recs


def _pct(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((len(s) - 1) * q))))
    return s[k]


def _rate(recs, key):
    xs = [r[key] for r in recs if r.get(key) is not None]
    return (sum(1 for x in xs if x) / len(xs), len(xs)) if xs else (None, 0)


def summarize(recs, n_runs):
    def rate_line(label, key):
        r, n = _rate(recs, key)
        pct = f"{r * 100:5.1f}%" if r is not None else "  n/a"
        print(f"  {label:28} {pct}   (n={n})")

    print("\n" + "=" * 64)
    print(f"Tier1 KPI 요약  (시나리오 {len(SCENARIOS)}개 × {n_runs}회 = 턴 {len(recs)}개)")
    print("=" * 64)
    print("[정확도]")
    rate_line("intent 정확도", "intent_ok")
    rate_line("category 분류 정확도(규칙)", "cat_ok")
    rate_line("가드레일 정확도", "guardrail_ok")
    rate_line("검색 성공률(answerable rag)", "retrieval_ok")
    rate_line("근거 확보율(expect_facts)", "facts_hit")
    rate_line("도구 성공률", "tool_ok")

    print("\n[지연 ms — router / retrieval(rag)·tool]")
    rms = [r["router_ms"] for r in recs if r.get("router_ms") is not None]
    sms = [r["stage_ms"] for r in recs if r.get("stage_ms") is not None]
    for label, vals in [("router", rms), ("stage(검색/도구)", sms)]:
        if vals:
            avg = sum(vals) / len(vals)
            print(
                f"  {label:18} avg {avg:7.1f}  p50 {_pct(vals, .5):7.1f}  p95 {_pct(vals, .95):7.1f}"
            )

    # 오분류 턴 리스트
    misses = [
        r
        for r in recs
        if not r["intent_ok"]
        or r.get("cat_ok") is False
        or r.get("guardrail_ok") is False
        or r.get("retrieval_ok") is False
    ]
    if misses:
        print(f"\n[주목: 라벨과 불일치 {len({(m['scenario'], m['turn']) for m in misses})}종]")
        seen = set()
        for m in misses:
            key = (m["scenario"], m["turn"])
            if key in seen:
                continue
            seen.add(key)
            flags = []
            if not m["intent_ok"]:
                flags.append(f"intent {m['exp_intent']}→{m['got_intent']}")
            if m.get("cat_ok") is False:
                flags.append(f"cat {m.get('exp_cat')}→{m.get('rule_cats')}")
            if m.get("guardrail_ok") is False:
                flags.append(f"guardrail={m.get('guardrail')}(answerable={m['answerable']})")
            if m.get("retrieval_ok") is False:
                flags.append(f"검색실패 top={m.get('top_score')}")
            print(f"  [{m['scenario']}/{m['turn']}] {m['q'][:32]!r}: {'; '.join(flags)}")


def main():
    n_runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    print(f"Tier1 평가 시작 (N={n_runs}, guardrail_threshold={THRESH})")
    recs = asyncio.run(run_all(n_runs))

    # 평가로 생긴 리마인드 예약 정리
    try:
        conn = db.connect()
        conn.execute("DELETE FROM reminder_requests WHERE session_id LIKE '__eval__%'")
        conn.close()
    except Exception as e:
        print("정리 실패:", e)

    os.makedirs(RESULT_DIR, exist_ok=True)
    with open(os.path.join(RESULT_DIR, "tier1_raw.json"), "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=2)
    summarize(recs, n_runs)
    print(f"\n원자료 저장: eval/results/tier1_raw.json ({len(recs)}건)")


if __name__ == "__main__":
    main()
