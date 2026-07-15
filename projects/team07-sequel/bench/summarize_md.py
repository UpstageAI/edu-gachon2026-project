"""모든 실험 조건(zero/few/schema/schema_few) 결과를 하나의 마크다운 리포트로 정리.

    uv run python -m bench.summarize_md            # docs/benchmark_routing.md 생성
    uv run python -m bench.summarize_md path.md
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from bench import config

LEVELS = config.HARDNESS_ORDER
MODELS = list(config.MODELS)
KO = config.HARDNESS_KO
ORDER = ["zero", "few", "schema", "schema_few"]  # 표시 순서


def _load(path):
    if not path.exists():
        return None
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _agg(rows):
    cell = defaultdict(lambda: {"n": 0, "ex": 0, "em": 0, "ptok": 0, "ctok": 0, "lat": 0.0, "cost": 0.0})
    for o in rows:
        c = cell[(o["model"], o["hardness"])]
        c["n"] += 1
        c["ex"] += int(o["ex"]); c["em"] += int(o["em"])
        c["ptok"] += o["prompt_tokens"]; c["ctok"] += o["completion_tokens"]
        c["lat"] += o["latency"]; c["cost"] += o["cost_usd"]
    return cell


def _cat(o):
    if o["error"]:
        return "api_error"
    if o["ex"]:
        return "correct"
    note = o.get("exec_note") or ""
    if note.startswith("gold-error"):
        return "gold_broken"
    return "exec_error" if note else "wrong_result"


def _overall(cell):
    n = sum(c["n"] for c in cell.values()); ex = sum(c["ex"] for c in cell.values())
    return ex, n, (ex / n * 100 if n else 0)


def _lvl_mean_ex(cell, lv):
    n = sum(cell[(m, lv)]["n"] for m in MODELS if (m, lv) in cell)
    ex = sum(cell[(m, lv)]["ex"] for m in MODELS if (m, lv) in cell)
    return ex / n * 100 if n else None


def _row(cells):
    return "| " + " | ".join(cells) + " |"


def _hdr(cols):
    return _row(cols) + "\n" + _row(["---"] * len(cols))


def _ex_table(cell):
    out = [_hdr(["난이도\\모델"] + MODELS)]
    for lv in LEVELS:
        cells = [KO[lv]]
        for m in MODELS:
            c = cell.get((m, lv))
            cells.append(f"{c['ex']/c['n']*100:.0f}% ({c['ex']}/{c['n']})" if c and c["n"] else "-")
        out.append(_row(cells))
    return "\n".join(out)


def _cost_table(cell):
    out = [_hdr(["난이도\\모델"] + MODELS)]
    for lv in LEVELS:
        cells = [KO[lv]]
        for m in MODELS:
            c = cell.get((m, lv))
            if not c or not c["n"]:
                cells.append("-"); continue
            pc = "∞" if c["ex"] == 0 else f"${c['cost']/c['ex']:.5f}"
            cells.append(f"${c['cost']/c['n']:.5f} / {pc}")
        out.append(_row(cells))
    return "\n".join(out)


def _routing(cell):
    out = [_hdr(["난이도", "추천 모델", "EX", "정답당 비용", "근거"])]
    rule = {}
    for lv in LEVELS:
        cand = [(m, cell[(m, lv)]["ex"] / cell[(m, lv)]["n"],
                 cell[(m, lv)]["cost"] / cell[(m, lv)]["ex"] if cell[(m, lv)]["ex"] else float("inf"))
                for m in MODELS if (m, lv) in cell and cell[(m, lv)]["n"]]
        if not cand:
            out.append(_row([KO[lv], "-", "-", "-", "데이터 없음"])); continue
        passing = [x for x in cand if x[1] >= config.ROUTING_EX_TARGET]
        if passing:
            m, ex, pc = min(passing, key=lambda x: x[2]); why = "목표 충족 최저가"
        else:
            m, ex, pc = max(cand, key=lambda x: x[1]); why = "목표 미달, EX 최고"
        rule[lv] = m
        pcs = "∞" if pc == float("inf") else f"${pc:.5f}"
        out.append(_row([KO[lv], m, f"{ex*100:.0f}%", pcs, why]))
    return "\n".join(out), rule


def _before_after(zrows, brows, eval_path, k=3):
    zmap = {(o["id"], o["model"]): o for o in zrows}
    emap = {r["id"]: r for r in json.loads(eval_path.read_text(encoding="utf-8"))}
    picks, seen = [], set()
    for o in brows:
        z = zmap.get((o["id"], o["model"]))
        if z and o["ex"] and not z["ex"] and not z["error"]:
            e = emap.get(o["id"], {}); q = e.get("question", "")
            if q in seen:
                continue
            seen.add(q)
            picks.append((o["model"], q, e.get("gold_sql", ""), z["pred_sql"], o["pred_sql"]))
        if len(picks) >= k:
            break
    if not picks:
        return ""
    lines = []
    for m, q, gold, zp, fp in picks:
        lines += [f"**[{m}] {q}**", "", f"- gold: `{gold}`",
                  f"- zero-shot: `{zp}` ✗", f"- 개선조건: `{fp}` ○", ""]
    return "\n".join(lines)


def main() -> None:
    out_path = config.BENCH_DIR.parents[0] / "docs" / "benchmark_routing.md"
    if len(sys.argv) > 1:
        out_path = Path(sys.argv[1])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    present = {}
    for cond in ORDER:
        rows = _load(config.CONDITIONS[cond][1])
        if rows:
            present[cond] = (rows, _agg(rows))
    if "zero" not in present:
        raise SystemExit("zero-shot 결과 없음")

    price = "\n".join(f"| {m} | ${p['in']:.2f} | ${p['out']:.2f} |" for m, p in config.MODELS.items())
    n_items = _overall(present["zero"][1])[1] // len(MODELS)

    md = [
        "# Sequel — Solar 모델 라우팅 벤치마크 (조건별 ablation)",
        "",
        "난이도(하/중/상/최상)별로 solar-mini / pro2 / pro3 의 Text-to-SQL 성능을 비교해,",
        "어느 난이도를 어느 모델로 라우팅할지 근거를 만든다.",
        "",
        "## 실험 설정",
        "",
        f"- **데이터**: AI Hub NL2SQL Validation, 난이도별 {config.SAMPLES_PER_LEVEL}문항 × 4 = {n_items}문항 (seed {config.SEED})",
        "- **난이도**: easy→하, medium→중, hard→상, extra hard→최상",
        "- **지표**: EX(실행결과 일치, 핵심) · 문항당/정답당 비용 · 토큰 · 지연",
        "- **조건 (2×2)**:",
        "  - `zero-shot` — 스키마 DDL만",
        "  - `few-shot` — DDL + 같은 DB 유사질문 예시 " + str(config.FEWSHOT_K) + "개",
        "  - `schema-linker` — DDL + 컬럼별 샘플 값(value_retriever), few-shot 없음",
        "  - `schema+few` — DDL + 샘플 값 + few-shot",
        "- **모델 단가** (USD / 1M tokens, upstage.ai/pricing/api):",
        "",
        _hdr(["모델", "입력", "출력"]),
        price,
        "",
        "---",
        "",
        "## 1. 요약 — 조건별 전체 EX",
        "",
        _hdr(["조건", "전체 EX"] + [KO[lv] for lv in LEVELS]),
    ]
    zpct = _overall(present["zero"][1])[2]
    for cond in ORDER:
        if cond not in present:
            continue
        cell = present[cond][1]
        ex, n, pct = _overall(cell)
        delta = "" if cond == "zero" else f" ({pct - zpct:+.0f}%p)"
        lvls = [f"{_lvl_mean_ex(cell, lv):.0f}%" for lv in LEVELS]
        md.append(_row([config.CONDITION_LABELS[cond], f"**{pct:.0f}%** ({ex}/{n}){delta}"] + lvls))
    md += ["", "_난이도 칸은 3모델 평균 EX._", "", "---", ""]

    # 조건별 상세 EX(모델별)
    md += ["## 2. 조건별 EX (모델별)", ""]
    for cond in ORDER:
        if cond not in present:
            continue
        rows, cell = present[cond]
        fc = Counter(_cat(o) for o in rows)
        md += [f"### {config.CONDITION_LABELS[cond]}",
               f"실패유형: correct {fc['correct']} · wrong_result {fc['wrong_result']} · "
               f"exec_error {fc['exec_error']} · api_error {fc['api_error']}", "",
               _ex_table(cell), ""]
    md += ["---", ""]

    # 최고 조건 → 라우팅 + 비용
    best = max(present, key=lambda c: _overall(present[c][1])[2])
    best_cell = present[best][1]
    routing_tbl, rule = _routing(best_cell)
    # pro2 vs pro3 지배 여부
    def _ex_ratio(cell) -> float:  # n 이 모델별로 다를 수 있어 비율로 비교
        return cell["ex"] / max(cell.get("n", 0), 1)
    pro3_dominated = all(
        _ex_ratio(best_cell[("solar-pro2", lv)]) >= _ex_ratio(best_cell[("solar-pro3", lv)])
        for lv in LEVELS if ("solar-pro2", lv) in best_cell and ("solar-pro3", lv) in best_cell)
    rule_txt = ", ".join(f"{KO[lv]}→{rule.get(lv, '-')}" for lv in LEVELS)

    md += [
        f"## 3. 라우팅 추천 (최고 조건: **{config.CONDITION_LABELS[best]}**)",
        "",
        routing_tbl, "",
        f"**라우팅 규칙: `{rule_txt}`**", "",
        ("- solar-pro3 는 모든 난이도에서 pro2 이하 EX (단가 동일) → 라우팅 후보에서 제외 가능."
         if pro3_dominated else "- solar-pro3 가 일부 난이도에서 pro2 를 앞섬 → 후보 유지 검토."),
        "",
        "### 최고 조건 — 문항당/정답당 비용", "", _cost_table(best_cell), "",
        "---", "",
    ]

    # before/after (best vs zero)
    ba = _before_after(present["zero"][0], present[best][0], config.CONDITIONS[best][0])
    if ba:
        md += [f"## 4. {config.CONDITION_LABELS[best]} 가 고친 사례 (zero-shot 틀림 → 개선조건 맞음)", "", ba, "---", ""]

    md += [
        "## 유의사항",
        "",
        "- EX 채점: gold/pred 를 같은 sqlite 에 실행해 결과셋 비교(순서 무시, gold 에 ORDER BY 시 순서 반영).",
        "- schema-linker = 컬럼별 distinct 샘플 값 " + str(config.SCHEMA_VALUE_K) + "개 주입(value_retriever 대용).",
        "- few-shot 예시는 val 풀 in-domain(약간 낙관적). held-out train 은 db_id disjoint 라 불가.",
        "- 표본 난이도별 " + str(config.SAMPLES_PER_LEVEL) + "문항 — 신뢰도 확보하려면 확대 필요.",
        "- 모델 문자열(solar-pro3)·단가는 계정/시점 기준으로 재확인 권장.",
        "- 원자료(eval_set/dbs/results)는 AI Hub 라이선스·용량상 미커밋. 본 리포트는 집계값.",
    ]

    out_path.write_text("\n".join(md), encoding="utf-8")
    print(f"작성 완료 → {out_path}  (조건 {len(present)}개: {', '.join(present)})")


if __name__ == "__main__":
    main()
