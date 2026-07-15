"""Tier2 평가 harness — 답변 품질 (심판 LLM).

전체 그래프(응답 LLM 포함)를 태워 실제 답변을 생성하고, 심판 LLM으로 채점한다:
  - grounded   : 답변의 사실이 [근거자료](검색문서/도구결과/문의처)에 있는가 (환각 판정)
  - source_cited: 답변이 출처/문의처/URL을 밝혔는가
  - relevance  : 질문 의도에 대한 답변의 유용성 (1~5)
가드레일 턴은 "모른다고 인정 + 문의처 안내"면 grounded=true로 본다.
reminder/ask_year 턴(결정적 템플릿, response 미경유)은 채점 생략(Tier1에서 검증).

사용법:  python -m eval.run_tier2 [N회반복=2]
"""

import asyncio
import json
import os
import sys
import time

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/gachon_ai")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_upstage import ChatUpstage  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from app import config, db  # noqa: E402
from app.graph import graph as gm  # noqa: E402
from app.repositories.contacts import format_contact  # noqa: E402
from eval.scenarios import SCENARIOS  # noqa: E402

RESULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


class Verdict(BaseModel):
    grounded: bool = Field(description="답변의 모든 사실 주장이 [근거자료]에 있으면 true")
    unsupported_claims: list[str] = Field(
        default_factory=list, description="근거에 없는데 단정한 사실"
    )
    source_cited: bool = Field(description="답변이 출처/문서명/URL/부서/전화 등을 밝혔으면 true")
    relevance: int = Field(description="질문 의도에 대한 답변의 유용성 1~5")
    reason: str = Field(description="판정 근거 한 줄")


JUDGE_PROMPT = """너는 가천대 인공지능학과 학사 챗봇의 답변을 평가하는 엄정한 심판이다.
[질문], [답변], [근거자료](챗봇이 참고한 문서/도구결과/문의처)를 보고 판정하라.

- grounded: [답변]의 사실 주장(숫자·학점·과목명·날짜·전화·규정)이 전부 [근거자료]에서 확인되면 true.
  근거에 없는 사실을 하나라도 지어냈으면 false.
- unsupported_claims: 근거에 없는데 답변이 단정한 사실 목록(없으면 빈 리스트).
- source_cited: 답변이 출처(문서명/URL/부서명/전화번호)를 밝혔으면 true.
- relevance: 질문 의도에 답이 얼마나 부합·유용한지 1(무관)~5(정확·충분).

[근거자료]가 "(자료 없음/문의처 안내)"로 시작하면 가드레일 상황이다:
답변이 '자료에서 확인 어렵다'고 솔직히 밝히고 제시된 문의처를 안내했으면 grounded=true,
없는 사실(벌점 점수·날짜·규정 등)을 지어냈으면 grounded=false로 판정하라."""


def get_judge():
    llm = ChatUpstage(
        api_key=config.UPSTAGE_API_KEY,
        model=config.LLM_MODEL,
        temperature=0.0,
        timeout=40,
        max_retries=2,
    )
    return llm.with_structured_output(Verdict)


def build_context(state):
    """심판에게 줄 [근거자료] — 응답 노드가 실제로 본 근거."""
    intent = state.get("intent")
    if intent == "rag" and state.get("guardrail"):
        return "(자료 없음/문의처 안내)\n" + format_contact(state.get("contact"))
    if intent == "rag":
        docs = state.get("retrieved_docs") or []
        return "\n".join(f"[자료{i + 1}] {d['content']}" for i, d in enumerate(docs)) or "(없음)"
    if intent == "tool":
        return json.dumps(state.get("tool_result"), ensure_ascii=False)
    return "(일반 대화 — 학사 사실 근거 불필요)"


async def run_all(n_runs):
    gm.set_checkpointer(MemorySaver())
    graph = gm.get_graph()
    judge = get_judge()
    recs = []
    # 레이트리밋(429) 완화용 턴 간 스로틀. 필요 시 EVAL_THROTTLE_S로 키운다.
    throttle = float(os.getenv("EVAL_THROTTLE_S", "0.5"))
    for run_idx in range(n_runs):
        for sc in SCENARIOS:
            tid = f"__t2__{sc['id']}_{run_idx}"
            for i, turn in enumerate(sc["turns"]):
                t0 = time.perf_counter()
                # 응답 LLM 호출(ainvoke) 실패(429 등)가 전체 실행을 죽이지 않도록 격리.
                # 한 턴이 실패해도 기록만 남기고 계속 진행해 부분 결과를 보존한다.
                try:
                    res = await graph.ainvoke(
                        {"messages": [HumanMessage(content=turn["q"])], "session_id": tid},
                        config={"configurable": {"thread_id": tid}},
                    )
                except Exception as e:  # noqa: BLE001
                    recs.append(
                        {
                            "run": run_idx,
                            "scenario": sc["id"],
                            "persona": sc["persona"],
                            "turn": i,
                            "q": turn["q"],
                            "judged": False,
                            "graph_error": str(e)[:140],
                        }
                    )
                    if throttle:
                        await asyncio.sleep(throttle)
                    continue
                e2e_ms = (time.perf_counter() - t0) * 1000
                intent = res.get("intent")
                answer = res["messages"][-1].content
                base = {
                    "run": run_idx,
                    "scenario": sc["id"],
                    "persona": sc["persona"],
                    "turn": i,
                    "q": turn["q"],
                    "intent": intent,
                    "answerable": turn["answerable"],
                    "expect_source": turn.get("expect_source"),
                    "e2e_ms": round(e2e_ms, 1),
                    "answer": answer,
                }
                # 결정적 템플릿(리마인드/되묻기)은 채점 생략
                if intent not in ("rag", "tool", "chat"):
                    base["judged"] = False
                    recs.append(base)
                    continue
                context = build_context(res)
                try:
                    v = await judge.ainvoke(
                        [
                            SystemMessage(content=JUDGE_PROMPT),
                            HumanMessage(
                                content=(
                                    f"[질문]\n{turn['q']}\n\n[답변]\n{answer}\n\n[근거자료]\n{context}"
                                    + (
                                        f"\n\n(참고) 기대 핵심사실: {turn['expect_facts']}"
                                        if turn.get("expect_facts")
                                        else ""
                                    )
                                )
                            ),
                        ]
                    )
                    base.update(
                        {
                            "judged": True,
                            "grounded": v.grounded,
                            "source_cited": v.source_cited,
                            "relevance": v.relevance,
                            "unsupported": v.unsupported_claims,
                            "judge_reason": v.reason,
                        }
                    )
                except Exception as e:  # noqa: BLE001
                    base.update({"judged": False, "judge_error": str(e)[:120]})
                recs.append(base)
                if throttle:
                    await asyncio.sleep(throttle)
        print(f"  run {run_idx + 1}/{n_runs} 완료")
    return recs


def _pct(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[max(0, min(len(s) - 1, int(round((len(s) - 1) * q))))]


def summarize(recs, n_runs):
    judged = [r for r in recs if r.get("judged")]

    def rate(pred, subset=None):
        xs = [r for r in (subset or judged) if r.get(pred) is not None]
        return (sum(1 for r in xs if r[pred]) / len(xs), len(xs)) if xs else (None, 0)

    print("\n" + "=" * 64)
    print(f"Tier2 답변품질 요약  (판정 턴 {len(judged)} / 전체 {len(recs)}, N={n_runs})")
    print("=" * 64)
    errs = [r for r in recs if r.get("graph_error") or r.get("judge_error")]
    if errs:
        print(f"  ⚠ LLM 호출 실패 {len(errs)}턴 (레이트리밋 등) — 부분 결과로 집계")

    gr, ng = rate("grounded")
    print(
        f"  grounded(근거일치)율        {gr * 100:5.1f}%   (n={ng})   → 환각율 {(1 - gr) * 100:.1f}%"
    )

    src_subset = [r for r in judged if r.get("expect_source")]
    sr, ns = rate("source_cited", src_subset)
    print(f"  출처 인용률(expect_source)  {sr * 100:5.1f}%   (n={ns})")

    rels = [r["relevance"] for r in judged if r.get("relevance") is not None]
    if rels:
        avg = sum(rels) / len(rels)
        print(f"  평균 관련도                 {avg:.2f}/5 ({avg / 5 * 100:.0f}%)   (n={len(rels)})")

    # 가드레일 턴: 환각 없이 정직하게 안내했는가
    guard = [r for r in judged if not r["answerable"]]
    if guard:
        ggr, _ = rate("grounded", guard)
        print(f"  가드레일 정직도(grounded)   {ggr * 100:5.1f}%   (n={len(guard)})")

    e2e = [r["e2e_ms"] for r in recs if r.get("e2e_ms") is not None]
    if e2e:
        print("\n[e2e 지연 ms — 응답 LLM 포함]")
        print(
            f"  avg {sum(e2e) / len(e2e):7.1f}  p50 {_pct(e2e, .5):7.1f}  p95 {_pct(e2e, .95):7.1f}"
        )

    # 문제 케이스
    bad = [r for r in judged if r.get("grounded") is False or (r.get("relevance") or 5) <= 2]
    if bad:
        print(f"\n[주목: 환각/저관련 {len(bad)}건]")
        for r in bad:
            print(
                f"  [{r['scenario']}/{r['turn']}] {r['q'][:30]!r} grounded={r.get('grounded')} "
                f"rel={r.get('relevance')} unsupported={r.get('unsupported')}"
            )


def main():
    n_runs = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    print(f"Tier2 평가 시작 (N={n_runs}) — 응답 LLM + 심판 LLM 호출")
    recs = asyncio.run(run_all(n_runs))
    try:
        conn = db.connect()
        conn.execute("DELETE FROM reminder_requests WHERE session_id LIKE '__t2__%'")
        conn.close()
    except Exception as e:  # noqa: BLE001
        print("정리 실패:", e)
    os.makedirs(RESULT_DIR, exist_ok=True)
    with open(os.path.join(RESULT_DIR, "tier2_raw.json"), "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=2)
    summarize(recs, n_runs)
    print(f"\n원자료 저장: eval/results/tier2_raw.json ({len(recs)}건)")


if __name__ == "__main__":
    main()
