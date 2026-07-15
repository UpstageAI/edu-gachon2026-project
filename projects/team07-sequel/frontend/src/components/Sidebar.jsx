/** 좌측 고정 사이드바 — 로고 · 새 질문 · 메뉴 · 데이터소스 · 사용자.
 *  데이터소스는 실제 연결 1개(Retail DB=Supabase)만 정직하게 표기한다. */
const NAV = [
  { key: "home", icon: "⌂", ko: "홈", en: "Home" },
  { key: "ask", icon: "✦", ko: "질문하기", en: "Ask" },
  { key: "history", icon: "↺", ko: "히스토리", en: "History" },
  { key: "saved", icon: "★", ko: "저장됨", en: "Saved" },
];

export default function Sidebar({ screen, onNav }) {
  return (
    <aside className="sidebar">
      <div className="logo-row">
        <div className="logo-sq">S</div>
        <div>
          <div className="logo-title">Sequel</div>
          <div className="logo-sub">Text → SQL</div>
        </div>
      </div>

      <button className="btn-primary" onClick={() => onNav("ask")}>
        <span style={{ fontSize: 16, lineHeight: 1 }}>＋</span> 새 질문
      </button>

      <div className="side-label">메뉴</div>
      <nav className="nav">
        {NAV.map((n) => (
          <button
            key={n.key}
            className={"nav-item" + (screen === n.key ? " active" : "")}
            onClick={() => onNav(n.key)}
          >
            <span className="ic">{n.icon}</span>
            <span className="ko">{n.ko}</span>
            <span className="en">{n.en}</span>
          </button>
        ))}
      </nav>

      <div className="side-label mt">데이터소스</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <div className="source-row">
          <span className="source-dot" style={{ background: "#16A34A" }} />
          <span className="source-name">Retail DB</span>
          <span className="source-count">연결됨</span>
        </div>
      </div>

      <div className="side-footer">
        <div className="avatar">지</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>지현 님</div>
          <div style={{ fontSize: 11, color: "var(--muted)" }}>마케팅팀</div>
        </div>
        <span style={{ color: "var(--muted)", fontSize: 15 }}>⌄</span>
      </div>
    </aside>
  );
}
