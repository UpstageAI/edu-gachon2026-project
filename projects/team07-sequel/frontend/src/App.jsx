import { useRef, useState } from "react";
import Sidebar from "./components/Sidebar.jsx";
import Home from "./screens/Home.jsx";
import Ask from "./screens/Ask.jsx";
import History from "./screens/History.jsx";
import Saved from "./screens/Saved.jsx";
import { streamQuery, fetchSuggestions } from "./api.js";
import { addHistory, toggleSaved } from "./store.js";

function uid() {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
}

export default function App() {
  const [screen, setScreen] = useState("home");
  const [turns, setTurns] = useState([]);
  const [followups, setFollowups] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [schemaOpen, setSchemaOpen] = useState(false);

  // 한 접속 = 세션 하나 (새로고침 전까지 유지). 히스토리 병합·후속질문의 키.
  const sessionId = useRef(uid());
  // 가장 최근 턴 id — 비동기 후속질문이 뒤늦게 도착해도 지난 턴 것으로 덮지 않게.
  const latestTurn = useRef(null);

  function patchTurn(id, patch) {
    setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)));
  }

  async function runQuery(question) {
    if (isStreaming) return;
    const id = uid();
    latestTurn.current = id;
    setTurns((prev) => [
      ...prev,
      { id, question, status: "요청을 보내는 중…", view: "table", done: false },
    ]);
    setFollowups([]);
    setIsStreaming(true);

    let tables = [];
    try {
      await streamQuery({
        question,
        sessionId: sessionId.current,
        onEvent: (e) => {
          if (e.type === "status") {
            patchTurn(id, { status: e.label });
          } else if (e.type === "route") {
            patchTurn(id, { difficulty: e.difficulty, model: e.model });
          } else if (e.type === "tables") {
            tables = e.tables;
          } else if (e.type === "done") {
            const a = e.answer || {};
            const table = a.table || { columns: [], rows: [] };
            patchTurn(id, {
              status: null,
              summary: a.summary || "",
              sql: a.sql || "",
              table,
              meta: a.meta || null,
              error: a.error || null,
              done: true,
            });
            if (table.rows && table.rows.length > 0) {
              addHistory({
                q: question,
                rowCount: table.rows.length,
                tables: tables.slice(0, 3).join(", "),
              });
            }
          } else if (e.type === "error") {
            patchTurn(id, { status: null, error: e.message, done: true });
          }
        },
      });
      // 후속질문은 스트림에서 떼어 비동기로 — 답변은 이미 표시됐으니 입력/스트리밍을 막지 않는다.
      // 뒤늦게 도착하면 그때 채우되, 그 사이 새 턴이 시작됐으면(latestTurn 불일치) 무시한다.
      fetchSuggestions(sessionId.current)
        .then((sugg) => {
          if (latestTurn.current === id) setFollowups(sugg);
        })
        .catch(() => {});
    } catch (err) {
      patchTurn(id, { status: null, error: err?.message || "알 수 없는 오류가 발생했습니다.", done: true });
    } finally {
      setIsStreaming(false);
    }
  }

  // 홈/히스토리/저장에서 질문 클릭 → Ask 로 이동 + 즉시 실행
  function askQuestion(q) {
    setScreen("ask");
    runQuery(q);
  }

  return (
    <div className="shell">
      <Sidebar screen={screen} onNav={setScreen} />
      <main className="main">
        {screen === "home" && <Home onAsk={askQuestion} onNav={setScreen} />}
        {screen === "ask" && (
          <Ask
            turns={turns}
            followups={followups}
            isStreaming={isStreaming}
            schemaOpen={schemaOpen}
            onToggleSchema={() => setSchemaOpen((v) => !v)}
            onSend={runQuery}
            onSetView={(id, view) => patchTurn(id, { view })}
            onToggleSave={(t) => toggleSaved({ id: t.id, q: t.question, summary: t.summary })}
          />
        )}
        {screen === "history" && <History onAsk={askQuestion} />}
        {screen === "saved" && <Saved onAsk={askQuestion} />}
      </main>
    </div>
  );
}
