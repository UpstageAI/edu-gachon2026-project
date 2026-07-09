"""Solar 라우팅 벤치마크: 모델 호출 → EM/EX 채점 → 난이도별 성능·비용 리포트.

    uv run python -m bench.bench run       # 모델 x 문항 실행 (UPSTAGE_API_KEY 필요, 유료)
    uv run python -m bench.bench report    # results.jsonl → 표 + 라우팅 추천

run 은 results.jsonl 에 (id, model) 단위로 append 하며, 이미 한 조합은 건너뛴다(재개 가능).
"""
from __future__ import annotations

import argparse
import json
import os
import time

import httpx

from bench import config, evaluate

SYSTEM = (
    "You are a Text-to-SQL generator for a read-only SQLite database. "
    "Given the schema and a Korean question, output exactly one SQL SELECT query. "
    "No explanation, no markdown fences — just the SQL."
)


def _prompt(schema: str, question: str, fewshot=None) -> str:
    ex = ""
    if fewshot:
        lines = "\n".join(f"Q: {s['question']}\nSQL: {s['sql']}" for s in fewshot)
        ex = f"\n\n# Examples (same database)\n{lines}"
    return f"# Schema\n{schema}{ex}\n\n# Question\n{question}\n\n# SQL"


def generate_sql(model: str, schema: str, question: str, api_key: str, fewshot=None) -> dict:
    """모델 1회 호출 → {sql, prompt_tokens, completion_tokens, latency, error}."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": _prompt(schema, question, fewshot)},
        ],
        "temperature": config.TEMPERATURE,
        "max_tokens": config.MAX_TOKENS,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"{config.UPSTAGE_BASE_URL}/chat/completions"
    last_err = None
    for attempt in range(3):  # 일시 오류 재시도
        t0 = time.perf_counter()
        try:
            r = httpx.post(url, headers=headers, json=payload, timeout=config.REQUEST_TIMEOUT)
            r.raise_for_status()
            d = r.json()
            u = d.get("usage", {})
            raw = d["choices"][0]["message"]["content"]
            return {
                "sql": evaluate.extract_sql(raw),
                "prompt_tokens": u.get("prompt_tokens", 0),
                "completion_tokens": u.get("completion_tokens", 0),
                "latency": time.perf_counter() - t0,
                "error": None,
            }
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(1.5 * (attempt + 1))
    return {"sql": "", "prompt_tokens": 0, "completion_tokens": 0, "latency": 0.0, "error": last_err}


def _done_keys(results_path) -> set[tuple[str, str]]:
    if not results_path.exists():
        return set()
    keys = set()
    for line in results_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            keys.add((o["id"], o["model"]))
    return keys


def cmd_run(args) -> None:
    api_key = os.getenv("UPSTAGE_API_KEY", "")
    if not api_key:
        raise SystemExit("UPSTAGE_API_KEY 환경변수가 필요합니다 (.env 또는 export).")
    eval_set, results_path = config.CONDITIONS[args.cond]
    if not eval_set.exists():
        raise SystemExit(f"{eval_set.name} 없음 — 먼저 build 스크립트 실행")

    records = json.loads(eval_set.read_text(encoding="utf-8"))
    done = _done_keys(results_path)
    models = list(config.MODELS)
    todo = [(r, m) for r in records for m in models if (r["id"], m) not in done]
    print(f"[{config.CONDITION_LABELS[args.cond]}] 문항 {len(records)} × 모델 {len(models)} "
          f"→ 남은 호출 {len(todo)} (완료 {len(done)})")

    spent = 0.0
    with results_path.open("a", encoding="utf-8") as fout:
        for i, (r, model) in enumerate(todo, 1):
            gen = generate_sql(model, r["schema"], r["question"], api_key, r.get("fewshot"))
            db = str(config.DB_DIR / f"{r['db_id']}.sqlite")
            if gen["error"]:
                em = ex = False
                exerr = gen["error"]
            else:
                em = evaluate.exact_match(gen["sql"], r["gold_sql"])
                ex, exerr = evaluate.exec_match(gen["sql"], r["gold_sql"], db, config.EXEC_TIMEOUT_S)
            cost = config.price_usd(model, gen["prompt_tokens"], gen["completion_tokens"])
            spent += cost
            row = {
                "id": r["id"], "hardness": r["hardness"], "level_ko": r["level_ko"],
                "model": model, "em": em, "ex": ex,
                "prompt_tokens": gen["prompt_tokens"], "completion_tokens": gen["completion_tokens"],
                "latency": round(gen["latency"], 3), "cost_usd": cost,
                "error": gen["error"], "exec_note": None if ex else exerr,
                "pred_sql": gen["sql"],
            }
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
            fout.flush()
            mark = "○" if ex else ("△" if em else "✗")
            print(f"[{i}/{len(todo)}] {r['level_ko']} {model:10s} {mark} "
                  f"tok {gen['prompt_tokens']}+{gen['completion_tokens']} ${spent:.4f}")
    print(f"\n완료. 누적 비용 ≈ ${spent:.4f}. 리포트: python -m bench.bench report --cond {args.cond}")


def _agg(rows: list[dict]):
    from collections import defaultdict
    cell = defaultdict(lambda: {"n": 0, "ex": 0, "em": 0, "ptok": 0, "ctok": 0, "lat": 0.0, "cost": 0.0})
    for o in rows:
        c = cell[(o["model"], o["hardness"])]
        c["n"] += 1
        c["ex"] += int(o["ex"])
        c["em"] += int(o["em"])
        c["ptok"] += o["prompt_tokens"]
        c["ctok"] += o["completion_tokens"]
        c["lat"] += o["latency"]
        c["cost"] += o["cost_usd"]
    return cell


def cmd_report(args) -> None:
    _, results_path = config.CONDITIONS[args.cond]
    if not results_path.exists():
        raise SystemExit(f"{results_path.name} 없음 — 먼저 run.")
    rows = [json.loads(l) for l in results_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    cell = _agg(rows)
    models = list(config.MODELS)
    levels = config.HARDNESS_ORDER

    def line(cells):
        print("| " + " | ".join(cells) + " |")

    print("\n## 난이도 × 모델 — EX 성공률 (실행결과 일치)\n")
    line(["난이도\\모델"] + models)
    line(["---"] * (len(models) + 1))
    for lv in levels:
        cells = [config.HARDNESS_KO[lv]]
        for m in models:
            c = cell.get((m, lv))
            cells.append(f"{c['ex']/c['n']*100:.0f}% ({c['ex']}/{c['n']})" if c and c["n"] else "-")
        line(cells)

    print("\n## 난이도 × 모델 — 문항당 평균 비용(USD) · 정답당 비용\n")
    line(["난이도\\모델"] + models)
    line(["---"] * (len(models) + 1))
    for lv in levels:
        cells = [config.HARDNESS_KO[lv]]
        for m in models:
            c = cell.get((m, lv))
            if not c or not c["n"]:
                cells.append("-"); continue
            per_q = c["cost"] / c["n"]
            per_correct = c["cost"] / c["ex"] if c["ex"] else float("inf")
            pc = "∞" if c["ex"] == 0 else f"${per_correct:.5f}"
            cells.append(f"${per_q:.5f} / {pc}")
        line(cells)

    print("\n## 난이도 × 모델 — 평균 토큰(in+out) · 평균 지연(s)\n")
    line(["난이도\\모델"] + models)
    line(["---"] * (len(models) + 1))
    for lv in levels:
        cells = [config.HARDNESS_KO[lv]]
        for m in models:
            c = cell.get((m, lv))
            cells.append(
                f"{(c['ptok']+c['ctok'])/c['n']:.0f} / {c['lat']/c['n']:.1f}s" if c and c["n"] else "-")
        line(cells)

    # ── 라우팅 추천: 난이도별로, EX 목표 달성 모델 중 정답당 비용 최소 ──
    print(f"\n## 라우팅 추천 (EX ≥ {config.ROUTING_EX_TARGET*100:.0f}% 중 정답당 비용 최소)\n")
    line(["난이도", "추천 모델", "EX", "정답당 비용", "근거"])
    line(["---"] * 5)
    for lv in levels:
        cand = []
        for m in models:
            c = cell.get((m, lv))
            if not c or not c["n"]:
                continue
            ex_rate = c["ex"] / c["n"]
            per_correct = c["cost"] / c["ex"] if c["ex"] else float("inf")
            cand.append((m, ex_rate, per_correct))
        if not cand:
            line([config.HARDNESS_KO[lv], "-", "-", "-", "데이터 없음"]); continue
        passing = [x for x in cand if x[1] >= config.ROUTING_EX_TARGET]
        if passing:
            m, ex_rate, pc = min(passing, key=lambda x: x[2])
            why = "목표 충족 최저가"
        else:  # 아무도 목표 미달 → EX 최고
            m, ex_rate, pc = max(cand, key=lambda x: x[1])
            why = "목표 미달, EX 최고"
        line([config.HARDNESS_KO[lv], m, f"{ex_rate*100:.0f}%",
              "∞" if pc == float("inf") else f"${pc:.5f}", why])
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description="Solar NL2SQL 라우팅 벤치마크")
    conds = list(config.CONDITIONS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="모델 호출 + 채점 (유료)")
    p_run.add_argument("--cond", choices=conds, default="zero", help="실험 조건")
    p_rep = sub.add_parser("report", help="집계 표 + 라우팅 추천")
    p_rep.add_argument("--cond", choices=conds, default="zero", help="실험 조건")
    args = ap.parse_args()
    {"run": cmd_run, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
