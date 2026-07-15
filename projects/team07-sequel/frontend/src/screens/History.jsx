import { getHistory, relTime } from "../store.js";

export default function History({ onAsk }) {
  const rows = getHistory();
  return (
    <div className="screen">
      <div className="screen-inner" style={{ maxWidth: 840 }}>
        <h1 className="h1" style={{ fontSize: 26 }}>
          히스토리 <span className="en-dim" style={{ fontSize: 19 }}>History</span>
        </h1>
        <p className="sub" style={{ fontSize: 14 }}>지금까지 물어본 모든 질문입니다.</p>

        {rows.length === 0 ? (
          <div className="card empty" style={{ padding: 40 }}>
            아직 기록이 없어요. 질문을 하면 여기에 쌓입니다.
          </div>
        ) : (
          rows.map((h, i) => (
            <div key={i} className="card hist-row" onClick={() => onAsk(h.q)}>
              <span className="hist-ic">↺</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14.5, fontWeight: 600, marginBottom: 3 }} className="ellip">
                  {h.q}
                </div>
                <div style={{ fontSize: 12, color: "var(--muted)", display: "flex", gap: 10 }}>
                  <span>{relTime(h.ts)}</span>
                  <span>·</span>
                  <span>{h.rowCount} rows</span>
                  {h.tables ? (
                    <>
                      <span>·</span>
                      <span className="mono">{h.tables}</span>
                    </>
                  ) : null}
                </div>
              </div>
              <span className="badge-done">완료</span>
              <span style={{ color: "var(--faint)", fontSize: 17 }}>›</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
