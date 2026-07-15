import { useEffect, useState } from "react";
import { fetchMetrics } from "../api.js";
import { getHistory, getSaved, fmtInt, fmtCost, fmtLatency, relTime } from "../store.js";

// 오늘 날짜 한글 (2026년 7월 14일 화요일)
function todayKo() {
  const d = new Date();
  const days = ["일", "월", "화", "수", "목", "금", "토"];
  return `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일 ${days[d.getDay()]}요일`;
}

// /metrics KPI key → 카드 표시(라벨 + 값 포맷)
const KPI_META = {
  llm_calls: { label: "오늘 LLM 호출", fmt: fmtInt },
  avg_latency_ms: { label: "평균 응답", fmt: fmtLatency },
  total_tokens: { label: "오늘 토큰", fmt: fmtInt },
  cost_usd: { label: "오늘 비용", fmt: fmtCost },
};
const KPI_ORDER = ["llm_calls", "avg_latency_ms", "total_tokens", "cost_usd"];

const STARTERS = [
  "가장 많이 팔린 상품 카테고리 상위 10개",
  "월별 주문 수 추이",
  "평균 배송 소요일은?",
];

function Delta({ pct }) {
  if (pct == null) return <span className="kpi-delta flat">어제 대비 —</span>;
  const cls = pct > 0 ? "up" : pct < 0 ? "down" : "flat";
  const arrow = pct > 0 ? "▲" : pct < 0 ? "▼" : "―";
  return (
    <span className={"kpi-delta " + cls}>
      {arrow} {Math.abs(pct)}% <span style={{ color: "var(--muted)", fontWeight: 500 }}>어제 대비</span>
    </span>
  );
}

export default function Home({ onAsk, onNav }) {
  const [metrics, setMetrics] = useState(null);
  const [history] = useState(getHistory);
  const [saved] = useState(getSaved);

  useEffect(() => {
    fetchMetrics().then(setMetrics);
  }, []);

  const kpiByKey = {};
  if (metrics) for (const k of metrics.kpis) kpiByKey[k.key] = k;

  return (
    <div className="screen">
      <div className="screen-inner" style={{ maxWidth: 960 }}>
        <div className="date-line">{todayKo()}</div>
        <h1 className="h1" style={{ fontSize: 32 }}>
          안녕하세요, 지현 님 👋
        </h1>
        <p className="sub">무엇이 궁금하세요? 데이터에게 그냥 물어보세요.</p>

        <div className="ask-entry" onClick={() => onNav("ask")}>
          <span style={{ color: "var(--blue)", fontSize: 18 }}>✦</span>
          <span style={{ flex: 1, color: "var(--muted)", fontSize: 15 }}>
            예) 가장 많이 팔린 상품 카테고리 상위 10개를 보여줘…
          </span>
          <kbd className="kbd">⏎ Enter</kbd>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 36 }}>
          {STARTERS.map((q) => (
            <button key={q} className="chip" onClick={() => onAsk(q)}>
              {q}
            </button>
          ))}
        </div>

        {/* KPI — 실제 운영 지표(/metrics, Langfuse 집계). 비즈니스 KPI 대신 비용/토큰/지연. */}
        <div className="kpi-grid">
          {KPI_ORDER.map((key) => {
            const k = kpiByKey[key];
            const meta = KPI_META[key];
            const val = k ? meta.fmt(k.value) : metrics ? meta.fmt(0) : "—";
            return (
              <div key={key} className="card kpi">
                <div className="kpi-label">{meta.label}</div>
                <div className="kpi-value">{val}</div>
                {metrics && metrics.available ? (
                  <Delta pct={k ? k.delta_pct : null} />
                ) : (
                  <span className="kpi-delta flat">데이터 없음</span>
                )}
              </div>
            );
          })}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 22 }}>
          <div>
            <div className="section-head">
              <h2>
                최근 질문 <span className="en-dim">Recent</span>
              </h2>
              <a href="#" onClick={(e) => (e.preventDefault(), onNav("history"))}>
                전체 보기
              </a>
            </div>
            <div className="card list-card">
              {history.length === 0 ? (
                <div className="empty">아직 질문 기록이 없어요. 위에서 첫 질문을 해보세요.</div>
              ) : (
                history.slice(0, 4).map((r, i) => (
                  <div key={i} className="recent-row" onClick={() => onAsk(r.q)}>
                    <span className="ic-badge">↺</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="ellip" style={{ fontSize: 14, fontWeight: 500 }}>
                        {r.q}
                      </div>
                      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
                        {relTime(r.ts)} · {r.rowCount} rows
                      </div>
                    </div>
                    <span style={{ color: "var(--faint)", fontSize: 16 }}>›</span>
                  </div>
                ))
              )}
            </div>
          </div>

          <div>
            <div className="section-head">
              <h2>
                저장된 뷰 <span className="en-dim">Saved</span>
              </h2>
              <a href="#" onClick={(e) => (e.preventDefault(), onNav("saved"))}>
                전체 보기
              </a>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {saved.length === 0 ? (
                <div className="card empty">별표(★)로 저장한 질문이 여기 모여요.</div>
              ) : (
                saved.slice(0, 3).map((s) => (
                  <div
                    key={s.id}
                    className="card"
                    style={{ display: "flex", alignItems: "center", gap: 12, padding: "13px 15px", cursor: "pointer" }}
                    onClick={() => onAsk(s.q)}
                  >
                    <span className="ic-badge" style={{ width: 34, height: 34, borderRadius: 9, fontSize: 15 }}>
                      ★
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="ellip" style={{ fontSize: 13.5, fontWeight: 600 }}>
                        {s.q}
                      </div>
                      <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{relTime(s.ts)} 저장</div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
