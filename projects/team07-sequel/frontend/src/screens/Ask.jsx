import { useEffect, useRef, useState } from "react";
import SqlCard from "../components/SqlCard.jsx";
import ResultTable from "../components/ResultTable.jsx";
import ResultChart from "../components/ResultChart.jsx";
import Markdown from "../components/Markdown.jsx";
import { downloadCsv, fmtInt, fmtCost, fmtLatency, isSaved, toggleSaved } from "../store.js";
import { fetchSchema } from "../api.js";

function AssistantBlock({ turn, onSetView, onToggleSave, saved }) {
  const table = turn.table;
  const hasRows = table && table.rows && table.rows.length > 0;
  const chartable =
    hasRows && table.columns.some((_, i) => table.rows.every((r) => typeof r[i] === "number"));

  return (
    <div className="assist">
      <div className="q-avatar">S</div>
      <div className="assist-body">
        {turn.status ? (
          <div className="status-line">
            <span className="dot" />
            {turn.status}
          </div>
        ) : (
          <div className="meta-line">
            {turn.error ? (
              <span style={{ color: "var(--red)", fontWeight: 600 }}>처리 실패</span>
            ) : (
              <span>답변 완료</span>
            )}
            {turn.meta ? (
              <>
                <span className="sep">·</span>
                <span>{fmtLatency(turn.meta.latency_ms)}</span>
                <span className="sep">·</span>
                <span>{fmtInt(turn.meta.total_tokens)}토큰</span>
                <span className="sep">·</span>
                <span>{fmtCost(turn.meta.cost_usd)}</span>
              </>
            ) : null}
            {turn.difficulty ? (
              <>
                <span className="sep">·</span>
                <span>난이도 {turn.difficulty}</span>
              </>
            ) : null}
          </div>
        )}

        {turn.error && !turn.status ? (
          <Markdown text={turn.error} className="summary" style={{ color: "var(--red)" }} />
        ) : null}

        {turn.summary ? <Markdown text={turn.summary} className="summary" /> : null}

        {turn.sql ? <SqlCard sql={turn.sql} /> : null}

        {hasRows ? (
          <>
            <div className="result-bar">
              <span className="lbl">결과</span>
              <span className="meta">{table.rows.length} rows</span>
              <div style={{ flex: 1 }} />
              <div className="seg">
                <button className={turn.view === "table" ? "on" : ""} onClick={() => onSetView("table")}>
                  ▦ 표
                </button>
                <button
                  className={turn.view === "chart" ? "on" : ""}
                  onClick={() => onSetView("chart")}
                  disabled={!chartable}
                  title={chartable ? "" : "숫자 컬럼이 없어 차트를 그릴 수 없어요"}
                  style={!chartable ? { opacity: 0.4, cursor: "not-allowed" } : undefined}
                >
                  ▮ 차트
                </button>
              </div>
            </div>

            {turn.view === "chart" && chartable ? (
              <ResultChart columns={table.columns} rows={table.rows} />
            ) : (
              <ResultTable columns={table.columns} rows={table.rows} />
            )}

            <div className="actions">
              <button
                className={"btn-action" + (saved ? " done" : "")}
                onClick={onToggleSave}
              >
                {saved ? "★ 저장됨" : "★ 저장"}
              </button>
              <button
                className="btn-action"
                onClick={() => downloadCsv(table.columns, table.rows, "sequel_result.csv")}
              >
                ⭳ CSV 내보내기
              </button>
              <button className="btn-action" disabled title="대시보드 기능은 준비 중입니다">
                ＋ 대시보드에 추가
              </button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}

export default function Ask({
  turns,
  followups,
  isStreaming,
  schemaOpen,
  onToggleSchema,
  onSend,
  onSetView,
  onToggleSave,
}) {
  const [input, setInput] = useState("");
  const [savedTick, setSavedTick] = useState(0); // 저장 토글 후 재렌더 트리거
  const [schemaTables, setSchemaTables] = useState(null); // null=로딩전/중, []=실패, [...]=로드됨
  const [openTable, setOpenTable] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  // 스키마 패널을 처음 열 때 한 번만 로드 (api.js 에서 페이지당 캐시)
  useEffect(() => {
    if (schemaOpen && schemaTables === null) {
      fetchSchema().then((s) => setSchemaTables(s.tables || []));
    }
  }, [schemaOpen, schemaTables]);

  function submit() {
    const q = input.trim();
    if (!q || isStreaming) return;
    setInput("");
    onSend(q);
  }
  function onKey(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }
  function handleToggleSave(turn) {
    onToggleSave(turn);
    setSavedTick((t) => t + 1);
  }

  return (
    <div className="ask-cols">
      <div className="ask-main">
        <header className="ask-header">
          <h2>
            질문하기 <span className="en-dim">Ask</span>
          </h2>
          <span className="pill-green">
            <span className="d" />
            Retail DB 연결됨
          </span>
          <button className="btn-ghost" onClick={onToggleSchema}>
            ⊞ 스키마
          </button>
        </header>

        <div className="conv" ref={scrollRef}>
          <div className="conv-inner">
            {turns.length === 0 ? (
              <div className="empty" style={{ padding: "60px 0" }}>
                궁금한 걸 자연어로 물어보세요. 예) “가장 많이 팔린 상품 카테고리 상위 10개”
              </div>
            ) : (
              turns.map((t) => (
                <div key={t.id} className="turn">
                  <div className="user-line">
                    <div className="bubble-user">{t.question}</div>
                  </div>
                  <AssistantBlock
                    turn={t}
                    saved={isSaved(t.id)}
                    onSetView={(v) => onSetView(t.id, v)}
                    onToggleSave={() => handleToggleSave(t)}
                  />
                </div>
              ))
            )}
          </div>
        </div>

        <div className="composer">
          <div className="composer-inner">
            {followups.length > 0 ? (
              <div className="followups">
                {followups.map((q, i) => (
                  <button key={i} className="chip sm" onClick={() => setInput(q)}>
                    {q}
                  </button>
                ))}
              </div>
            ) : null}
            <div className="input-bar">
              <span style={{ color: "var(--blue)", fontSize: 17 }}>✦</span>
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKey}
                placeholder="후속 질문을 입력하세요…  예) 이 중에서 배송이 빠른 카테고리만"
                disabled={isStreaming}
              />
              <button className="send" onClick={submit} disabled={isStreaming || !input.trim()}>
                ↑
              </button>
            </div>
          </div>
        </div>
      </div>

      {schemaOpen ? (
        <aside className="rail">
          <div className="rail-head">
            <span className="t">
              스키마 <span className="en-dim">Schema</span>
            </span>
            <span className="rail-tag">Retail DB</span>
          </div>
          {schemaTables === null ? (
            <div className="empty" style={{ padding: "40px 18px" }}>불러오는 중…</div>
          ) : schemaTables.length === 0 ? (
            <div className="empty" style={{ padding: "40px 18px", lineHeight: 1.6 }}>
              스키마를 불러오지 못했어요.
            </div>
          ) : (
            <div className="schema-list">
              {schemaTables.map((t) => {
                const open = openTable === t.name;
                return (
                  <div key={t.name} className="schema-tbl">
                    <button className="schema-th" onClick={() => setOpenTable(open ? null : t.name)}>
                      <span className="tw">{open ? "▾" : "▸"}</span>
                      <span className="tn">{t.name}</span>
                      <span className="tc">{t.columns.length}</span>
                    </button>
                    {open ? (
                      <ul className="schema-cols">
                        {t.columns.map((c) => (
                          <li key={c.name}>
                            <span className="cn">{c.name}</span>
                            <span className="ct">{c.type}</span>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </aside>
      ) : null}
    </div>
  );
}
