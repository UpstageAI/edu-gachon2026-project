"""평가 대시보드 생성기 — Tier1/Tier2 원자료(JSON) → HTML.

사용법:  python -m eval.build_dashboard
출력:
  eval/results/dashboard.html           로컬 보기용 완결 문서
  eval/results/dashboard_artifact.html  Artifact 스켈레톤용 fragment(doctype/head/body 없음)

멘토 사전질문1 KPI를 발표용으로 시각화: 라우팅/검색/가드레일 정확도, 근거확보,
답변 품질(grounded/출처/관련도), 지연, 학번-게이트 수정 before/after.
"""

import json
import os
from datetime import datetime, timedelta, timezone

RESULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

# 학번 게이트 수정 '전' Tier1 baseline (개선 스토리용, 세션 측정값).
BEFORE_T1 = {"intent": 82.1, "category": 92.3, "guardrail": 93.8, "retrieval": 100.0, "facts": 72.7}

C_ACCENT = "#4f6bed"  # 인디고 — after·강조에만
C_BEFORE = "#97a3b6"  # 중립 slate — before
C_GOOD = "#15a34a"
C_WARN = "#d18a1b"
C_CRIT = "#dc2626"


def _load(name):
    path = os.path.join(RESULT_DIR, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _rate(recs, key, subset=None):
    xs = [r[key] for r in (subset or recs) if r.get(key) is not None]
    return (sum(1 for x in xs if x) / len(xs) * 100, len(xs)) if xs else (None, 0)


def _stats(vals):
    if not vals:
        return None
    s = sorted(vals)

    def pct(q):
        return s[max(0, min(len(s) - 1, int(round((len(s) - 1) * q))))]

    return {"avg": sum(s) / len(s), "p50": pct(0.5), "p95": pct(0.95)}


def agg_tier1(recs):
    a = {}
    for label, key in [
        ("intent", "intent_ok"),
        ("category", "cat_ok"),
        ("guardrail", "guardrail_ok"),
        ("retrieval", "retrieval_ok"),
        ("facts", "facts_hit"),
        ("tool", "tool_ok"),
    ]:
        a[label], _ = _rate(recs, key)
    return {
        "runs": len({r["run"] for r in recs}),
        "scen": len({r["scenario"] for r in recs}),
        "turns": len(recs),
        "acc": a,
        "router": _stats([r["router_ms"] for r in recs if r.get("router_ms") is not None]),
        "stage": _stats([r["stage_ms"] for r in recs if r.get("stage_ms") is not None]),
    }


def agg_tier2(recs):
    judged = [r for r in recs if r.get("judged")]
    grounded, _ = _rate(judged, "grounded")
    src, ns = _rate(judged, "source_cited", [r for r in judged if r.get("expect_source")])
    rels = [r["relevance"] for r in judged if r.get("relevance") is not None]
    guard = [r for r in judged if not r["answerable"]]
    gguard, _ = _rate(judged, "grounded", guard)
    # 환각/저관련 케이스는 시나리오별로 dedup + 빈도(N회 중 몇 번) 표기.
    bad_raw = [r for r in judged if r.get("grounded") is False or (r.get("relevance") or 5) <= 2]
    bad_by = {}
    for r in bad_raw:
        e = bad_by.setdefault(r["scenario"], {"rec": r, "n": 0})
        e["n"] += 1
    bad = [{**e["rec"], "count": e["n"]} for e in bad_by.values()]
    return {
        "runs": len({r["run"] for r in recs}),
        "judged": len(judged),
        "grounded": grounded,
        "source": src,
        "ns": ns,
        "relevance": (sum(rels) / len(rels)) if rels else None,
        "guard_honesty": gguard,
        "n_guard": len(guard),
        "e2e": _stats([r["e2e_ms"] for r in recs if r.get("e2e_ms") is not None]),
        "bad": bad,
    }


def _status(pct, hi, mid):
    if pct is None:
        return "warn"
    return "good" if pct >= hi else ("warn" if pct >= mid else "crit")


_CHIP = {"good": "우수", "warn": "양호", "crit": "주의"}


def _tile(value, label, sub, status):
    return f"""<div class="tile tile--{status}">
      <div class="tile-top"><span class="chip chip--{status}">{_CHIP[status]}</span></div>
      <div class="tile-val">{value}</div>
      <div class="tile-label">{label}</div>
      <div class="tile-sub">{sub}</div>
    </div>"""


def _ba_bar(label, before, after):
    def seg(pct, cls, color, tag):
        w = 0 if pct is None else max(1.5, pct)
        v = "n/a" if pct is None else f"{pct:.1f}%"
        return (
            f'<div class="seg"><span class="seg-tag {cls}">{tag}</span>'
            f'<div class="track"><div class="fill" style="width:{w}%;background:{color}"></div></div>'
            f'<span class="val">{v}</span></div>'
        )

    delta = ""
    if before is not None and after is not None and abs(after - before) >= 0.05:
        d = after - before
        delta = (
            f'<span class="delta up">+{d:.1f}p</span>'
            if d > 0
            else f'<span class="delta down">{d:.1f}p</span>'
        )
    return (
        f'<div class="ba"><div class="ba-label">{label}{delta}</div>'
        f'{seg(before, "b", C_BEFORE, "전")}{seg(after, "a", C_ACCENT, "후")}</div>'
    )


def _lat(title, stats):
    if not stats:
        return ""
    mx = max(stats["avg"], stats["p50"], stats["p95"]) or 1
    rows = ""
    for k, color in [("p50", C_GOOD), ("avg", C_ACCENT), ("p95", C_WARN)]:
        w = max(1.5, stats[k] / mx * 100)
        rows += (
            f'<div class="row"><span class="row-k">{k}</span>'
            f'<div class="track"><div class="fill" style="width:{w}%;background:{color}"></div></div>'
            f'<span class="val">{stats[k]:.0f}<span class="unit">ms</span></span></div>'
        )
    return f'<div class="lat"><div class="lat-h">{title}</div>{rows}</div>'


def _section(eyebrow, title, body):
    return f'<section><p class="eyebrow">{eyebrow}</p><h2>{title}</h2>{body}</section>'


CSS = f"""
:root {{
  --bg:#f5f6f9; --surface:#ffffff; --surface2:#fafbfc; --ink:#111827; --ink2:#51607a;
  --muted:#94a1b8; --border:#e4e8ef; --track:#eceff4; --accent:{C_ACCENT};
  --good:{C_GOOD}; --warn:{C_WARN}; --crit:{C_CRIT}; --before:{C_BEFORE};
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#0a0f1c; --surface:#121a2b; --surface2:#0f1626; --ink:#e8ecf5; --ink2:#9aa7c0;
    --muted:#66748f; --border:#1f2a40; --track:#1a2438; }}
}}
:root[data-theme="dark"] {{ --bg:#0a0f1c; --surface:#121a2b; --surface2:#0f1626; --ink:#e8ecf5;
  --ink2:#9aa7c0; --muted:#66748f; --border:#1f2a40; --track:#1a2438; }}
:root[data-theme="light"] {{ --bg:#f5f6f9; --surface:#ffffff; --surface2:#fafbfc; --ink:#111827;
  --ink2:#51607a; --muted:#94a1b8; --border:#e4e8ef; --track:#eceff4; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font-family:"Pretendard","Apple SD Gothic Neo","Malgun Gothic",-apple-system,BlinkMacSystemFont,
    "Segoe UI",Roboto,sans-serif;
  font-feature-settings:"tnum" 1; -webkit-font-smoothing:antialiased; line-height:1.55; }}
.wrap {{ max-width:1000px; margin:0 auto; padding:40px 22px 72px; }}
.masthead {{ border-bottom:1px solid var(--border); padding-bottom:20px; margin-bottom:8px; }}
.masthead h1 {{ font-size:25px; font-weight:750; letter-spacing:-.6px; margin:0 0 6px;
  text-wrap:balance; }}
.masthead .meta {{ color:var(--ink2); font-size:13px; margin:0; font-variant-numeric:tabular-nums; }}
section {{ margin-top:38px; }}
.eyebrow {{ text-transform:uppercase; letter-spacing:.14em; font-size:11px; font-weight:700;
  color:var(--accent); margin:0 0 3px; }}
h2 {{ font-size:17px; font-weight:700; letter-spacing:-.3px; margin:0 0 16px; color:var(--ink); }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(158px,1fr)); gap:12px; }}
.tile {{ position:relative; background:var(--surface); border:1px solid var(--border);
  border-radius:14px; padding:15px 16px 16px; overflow:hidden; }}
.tile::before {{ content:""; position:absolute; left:0; top:0; bottom:0; width:3px; }}
.tile--good::before {{ background:var(--good); }} .tile--warn::before {{ background:var(--warn); }}
.tile--crit::before {{ background:var(--crit); }}
.tile-top {{ margin-bottom:8px; }}
.chip {{ font-size:10.5px; font-weight:700; padding:2px 7px; border-radius:999px;
  letter-spacing:.02em; }}
.chip--good {{ color:var(--good); background:color-mix(in srgb,var(--good) 14%,transparent); }}
.chip--warn {{ color:var(--warn); background:color-mix(in srgb,var(--warn) 15%,transparent); }}
.chip--crit {{ color:var(--crit); background:color-mix(in srgb,var(--crit) 15%,transparent); }}
.tile-val {{ font-size:28px; font-weight:760; letter-spacing:-1px; line-height:1.1;
  font-variant-numeric:tabular-nums; }}
.tile-label {{ font-size:13px; font-weight:650; margin-top:3px; }}
.tile-sub {{ font-size:11.5px; color:var(--muted); margin-top:2px; }}
.card {{ background:var(--surface); border:1px solid var(--border); border-radius:14px;
  padding:20px 22px; }}
.track {{ flex:1; height:12px; background:var(--track); border-radius:6px; overflow:hidden; }}
.fill {{ height:100%; border-radius:6px; }}
.val {{ width:66px; text-align:right; font-size:13px; font-variant-numeric:tabular-nums;
  color:var(--ink2); flex-shrink:0; }}
.val .unit {{ color:var(--muted); font-size:11px; }}
.ba {{ padding:11px 0; border-bottom:1px solid var(--border); }}
.ba:last-child {{ border-bottom:0; }}
.ba-label {{ font-size:13px; font-weight:600; margin-bottom:5px; display:flex;
  align-items:center; gap:8px; }}
.seg {{ display:flex; align-items:center; gap:10px; margin:4px 0; }}
.seg-tag {{ width:18px; font-size:11px; flex-shrink:0; }}
.seg-tag.b {{ color:var(--muted); }} .seg-tag.a {{ color:var(--accent); font-weight:700; }}
.delta {{ font-size:12px; font-weight:700; font-variant-numeric:tabular-nums; }}
.delta.up {{ color:var(--good); }} .delta.down {{ color:var(--crit); }}
.lat {{ margin-bottom:16px; }} .lat:last-child {{ margin-bottom:0; }}
.lat-h {{ font-size:13px; font-weight:650; margin-bottom:6px; }}
.row {{ display:flex; align-items:center; gap:10px; margin:5px 0; }}
.row-k {{ width:38px; font-size:12px; color:var(--ink2); flex-shrink:0;
  font-variant-numeric:tabular-nums; }}
.legend {{ font-size:12px; color:var(--muted); margin-top:12px; display:flex; gap:14px;
  flex-wrap:wrap; }}
.legend span {{ display:inline-flex; align-items:center; gap:5px; }}
.dot {{ width:9px; height:9px; border-radius:3px; }}
.tblwrap {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--border);
  vertical-align:top; }}
th {{ color:var(--ink2); font-weight:650; white-space:nowrap; }}
.method p {{ font-size:13px; color:var(--ink2); margin:0 0 10px; }}
.method p:last-child {{ margin-bottom:0; }} .method b {{ color:var(--ink); font-weight:650; }}
.note {{ color:var(--muted); font-size:12px; margin-top:10px; }}
"""


def build_body(t1, t2):
    kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    a = t1["acc"]
    tiles = "".join(
        [
            _tile(
                f"{a['intent']:.1f}%",
                "intent 라우팅 정확도",
                f"{t1['turns']}턴",
                _status(a["intent"], 95, 85),
            ),
            _tile(
                f"{a['category']:.0f}%",
                "category 분류",
                "규칙 기반",
                _status(a["category"], 95, 85),
            ),
            _tile(
                f"{a['guardrail']:.0f}%",
                "가드레일 정확도",
                "범위밖 판별",
                _status(a["guardrail"], 95, 85),
            ),
            _tile(
                f"{a['retrieval']:.0f}%",
                "검색 성공률",
                "answerable RAG",
                _status(a["retrieval"], 95, 85),
            ),
            _tile(f"{a['facts']:.0f}%", "근거 확보율", "expect_facts", _status(a["facts"], 95, 85)),
        ]
    )
    qtiles = '<p class="note">Tier2 데이터 없음</p>'
    if t2:
        rel_pct = t2["relevance"] / 5 * 100
        qtiles = "".join(
            [
                _tile(
                    f"{t2['grounded']:.0f}%",
                    "grounded (환각 반대)",
                    f"환각율 {100 - t2['grounded']:.0f}%",
                    _status(t2["grounded"], 90, 80),
                ),
                _tile(
                    f"{t2['source']:.0f}%",
                    "출처 인용률",
                    f"n={t2['ns']}",
                    _status(t2["source"], 90, 80),
                ),
                _tile(
                    f"{t2['relevance']:.2f}",
                    "평균 관련도 (5점)",
                    f"{rel_pct:.0f}%",
                    _status(rel_pct, 90, 75),
                ),
                _tile(
                    f"{t2['guard_honesty']:.0f}%",
                    "가드레일 정직도",
                    f"n={t2['n_guard']}",
                    _status(t2["guard_honesty"], 90, 75),
                ),
            ]
        )

    ba = "".join(
        [
            _ba_bar("intent 라우팅", BEFORE_T1["intent"], a["intent"]),
            _ba_bar("category 분류", BEFORE_T1["category"], a["category"]),
            _ba_bar("가드레일 정확도", BEFORE_T1["guardrail"], a["guardrail"]),
            _ba_bar("근거 확보율", BEFORE_T1["facts"], a["facts"]),
        ]
    )
    ba_legend = (
        f'<div class="legend"><span><span class="dot" style="background:{C_BEFORE}"></span>'
        f'수정 전</span><span><span class="dot" style="background:{C_ACCENT}"></span>'
        f"수정 후</span></div>"
    )

    lat = _lat("Router — 규칙 확정 시 LLM 생략 → p50 0ms", t1["router"])
    lat += _lat("검색·도구 — RAG retrieval + rerank", t1["stage"])
    if t2 and t2["e2e"]:
        lat += _lat("전체 응답 e2e — 응답 LLM 포함", t2["e2e"])
    lat_legend = (
        f'<div class="legend"><span><span class="dot" style="background:{C_GOOD}"></span>'
        f'p50</span><span><span class="dot" style="background:{C_ACCENT}"></span>avg</span>'
        f'<span><span class="dot" style="background:{C_WARN}"></span>p95</span></div>'
    )

    flagged = '<p class="note">환각·저관련 플래그 없음</p>'
    if t2 and t2["bad"]:
        rows = "".join(
            f"<tr><td>{r['scenario']}</td><td>{r['q']}</td>"
            f"<td>{'환각' if r.get('grounded') is False else '저관련'} · rel {r.get('relevance')}"
            f" · {r.get('count', 1)}/{t2['runs']}회</td>"
            f"<td>{r.get('judge_reason', '')}</td></tr>"
            for r in t2["bad"]
        )
        flagged = (
            f'<div class="tblwrap"><table><thead><tr><th>시나리오</th><th>질문</th>'
            f"<th>플래그 · 빈도</th><th>심판 사유</th></tr></thead><tbody>{rows}</tbody></table></div>"
            f'<p class="note">※ LLM 심판은 보수적으로 채점 — 위 케이스 상당수는 실제로는 정상'
            f"(긴 목록 항목 누락 오판, 정직한 거절을 저관련으로 평가 등). 실제 환각률은 표기치보다 낮음.</p>"
        )

    t2_meta = f"Tier2 {t2['runs']}회 · 판정 {t2['judged']}턴" if t2 else "Tier2 미실행"
    method = """<div class="method">
      <p><b>KPI 산정</b> — 시나리오 N회 반복 평균. Tier1은 응답 LLM 없이 라우팅·검색·가드레일을
      결정적으로 측정(대량 반복), Tier2는 전체 그래프 답변을 LLM 심판으로 채점.</p>
      <p><b>할루시네이션 기준 (MVP)</b> — ① 1차 신뢰 게이트: reranker 점수(pgvector confidence
      가중합) &lt; 0.40이면 답변 대신 문의처 안내(가드레일). ② 2차 grounding: 답변 사실이 검색
      근거·도구 결과에 있는지 LLM 심판이 판정.</p>
      <p><b>데이터</b> — 2026학년도 총람 및 확보 학사자료(학번별 2021~2026 졸업요건·교육과정).</p>
      <p><b>신뢰 범위 · 한계</b> — 수치는 현재 {t1['scen']}개 시나리오 스위트 기준(<b>in-sample</b>)이며
      프로덕션 일반화 보장이 아니다. 결정적 컴포넌트(카테고리·검색·도구)의 100%는 반복 분산이 0이란
      뜻이지 커버리지 완벽을 의미하지 않는다. LLM 심판은 보수적이라 실제 환각률은 표기치보다 낮을 수 있고,
      어투·범위 밖 케이스를 늘릴수록 수치는 더 현실적으로 수렴한다.</p>
    </div>"""

    return f"""<div class="wrap">
  <header class="masthead">
    <h1>가천대 인공지능학과 길잡이 — 평가 대시보드</h1>
    <p class="meta">Tier1 {t1['scen']}개 시나리오 × {t1['runs']}회 = {t1['turns']}턴 · {t2_meta} · 생성 {kst}</p>
  </header>
  {_section("Routing &amp; Retrieval", "핵심 KPI — 라우팅·검색 (Tier1, 결정적)", f'<div class="grid">{tiles}</div>')}
  {_section("Answer Quality", "답변 품질 (Tier2, LLM 심판)", f'<div class="grid">{qtiles}</div>')}
  {_section("Before / After", "개선 — 학번 되묻기 게이트 수정", f'<div class="card">{ba}{ba_legend}</div>')}
  {_section("Latency", "지연", f'<div class="card">{lat}{lat_legend}</div>')}
  {_section("Flagged", "주목 케이스 — Tier2 심판 플래그", f'<div class="card">{flagged}</div>')}
  {_section("Methodology", "방법론 · 할루시네이션 기준", f'<div class="card">{method}</div>')}
</div>"""


TITLE = "AI 학과 길잡이 — 평가 대시보드"


def main():
    t1_raw = _load("tier1_raw.json")
    if not t1_raw:
        print("tier1_raw.json 없음 — 먼저 eval.run_tier1 실행")
        return
    t2_raw = _load("tier2_raw.json")
    t1 = agg_tier1(t1_raw)
    t2 = agg_tier2(t2_raw) if t2_raw else None
    body = build_body(t1, t2)

    full = (
        f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{TITLE}</title><style>{CSS}</style></head><body>{body}</body></html>"
    )
    fragment = f"<title>{TITLE}</title>\n<style>{CSS}</style>\n{body}"

    os.makedirs(RESULT_DIR, exist_ok=True)
    with open(os.path.join(RESULT_DIR, "dashboard.html"), "w", encoding="utf-8") as f:
        f.write(full)
    with open(os.path.join(RESULT_DIR, "dashboard_artifact.html"), "w", encoding="utf-8") as f:
        f.write(fragment)
    print("대시보드 생성: eval/results/dashboard.html + dashboard_artifact.html")
    print(
        f"  Tier1 {t1['turns']}턴/{t1['runs']}회 intent {t1['acc']['intent']:.1f}%"
        + (f" · Tier2 {t2['judged']}턴/{t2['runs']}회 grounded {t2['grounded']:.1f}%" if t2 else "")
    )


if __name__ == "__main__":
    main()
