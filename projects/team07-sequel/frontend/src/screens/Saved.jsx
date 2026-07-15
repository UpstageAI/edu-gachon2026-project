import { useState } from "react";
import { getSaved, toggleSaved, relTime } from "../store.js";
import { stripMarkdown } from "../components/Markdown.jsx";

export default function Saved({ onAsk }) {
  const [items, setItems] = useState(getSaved);

  function unstar(e, item) {
    e.stopPropagation();
    toggleSaved(item);
    setItems(getSaved());
  }

  return (
    <div className="screen">
      <div className="screen-inner" style={{ maxWidth: 960 }}>
        <h1 className="h1" style={{ fontSize: 26 }}>
          저장됨 <span className="en-dim" style={{ fontSize: 19 }}>Saved</span>
        </h1>
        <p className="sub" style={{ fontSize: 14 }}>자주 쓰는 질문을 별표로 모아뒀어요.</p>

        {items.length === 0 ? (
          <div className="card empty" style={{ padding: 40 }}>
            저장된 질문이 없어요. 답변 화면에서 ★ 저장을 눌러보세요.
          </div>
        ) : (
          <div className="saved-grid">
            {items.map((s) => (
              <div key={s.id} className="card saved-card" onClick={() => onAsk(s.q)}>
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
                  <span className="saved-ic" style={{ background: "#EFF4FF", color: "var(--blue)" }}>
                    ✦
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="ellip" style={{ fontSize: 15, fontWeight: 600 }}>
                      {s.q}
                    </div>
                    <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{relTime(s.ts)} 저장</div>
                  </div>
                  <span
                    style={{ color: "#F5B301", fontSize: 16, cursor: "pointer" }}
                    onClick={(e) => unstar(e, s)}
                    title="저장 해제"
                  >
                    ★
                  </span>
                </div>
                {s.summary ? (
                  <p style={{ fontSize: 13, color: "var(--t3)", margin: 0, lineHeight: 1.5 }} className="ellip">
                    {stripMarkdown(s.summary)}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
