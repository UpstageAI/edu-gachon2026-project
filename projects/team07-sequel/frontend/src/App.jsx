import { useRef, useState } from "react";
import ResultTable from "./components/ResultTable.jsx";
import { streamQuery } from "./api/queryStream.js";

function createId() {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
}

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [expandedSql, setExpandedSql] = useState({});

  // 대화 세션 식별자. 새로고침 전까지는 하나의 대화로 유지.
  const sessionIdRef = useRef(createId());

  function updateAssistant(id, patch) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, ...patch } : m))
    );
  }

  async function handleSend() {
    const question = input.trim();
    if (!question || isStreaming) return;

    setInput("");
    setIsStreaming(true);

    const userMsg = { id: createId(), role: "user", text: question };
    const assistantId = createId();
    const assistantMsg = {
      id: assistantId,
      role: "assistant",
      status: "요청을 보내는 중…",
      table: null,
      summary: null,
      sql: null,
      error: null,
      done: false,
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);

    try {
      await streamQuery({
        question,
        sessionId: sessionIdRef.current,
        onEvent: ({ type, data }) => {
          if (type === "status") {
            updateAssistant(assistantId, { status: data.message });
          } else if (type === "result") {
            updateAssistant(assistantId, {
              status: null,
              table: data.table,
              summary: data.summary,
            });
          } else if (type === "sql") {
            updateAssistant(assistantId, { sql: data.sql });
          } else if (type === "error") {
            updateAssistant(assistantId, { status: null, error: data.message });
          } else if (type === "done") {
            updateAssistant(assistantId, { done: true });
          }
        },
      });
    } catch (err) {
      updateAssistant(assistantId, {
        status: null,
        error: err?.message ?? "알 수 없는 오류가 발생했습니다.",
      });
    } finally {
      setIsStreaming(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function toggleSql(id) {
    setExpandedSql((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  return (
    <div className="app">
      <header className="app__header">
        <h1>Text2SQL 데이터 분석 비서</h1>
        <p>SQL을 몰라도 데이터베이스에 말로 질문하고 바로 답을 받아보세요.</p>
      </header>

      <div className="chat">
        {messages.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="message message--user">
              {m.text}
            </div>
          ) : (
            <div
              key={m.id}
              className={
                "message message--assistant" + (m.error ? " message--error" : "")
              }
            >
              {m.status && (
                <div className="status-line">
                  <span className="dot" />
                  {m.status}
                </div>
              )}

              {m.error && <div>{m.error}</div>}

              {m.summary && <p className="summary">{m.summary}</p>}

              {m.table && <ResultTable rows={m.table} />}

              {m.sql && (
                <div>
                  <button className="sql-toggle" onClick={() => toggleSql(m.id)}>
                    {expandedSql[m.id] ? "SQL 숨기기" : "SQL 보기"}
                  </button>
                  {expandedSql[m.id] && <pre className="sql-block">{m.sql}</pre>}
                </div>
              )}
            </div>
          )
        )}
      </div>

      <div className="composer">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="예: 이번 달 카테고리별 매출 알려줘"
          disabled={isStreaming}
        />
        <button onClick={handleSend} disabled={isStreaming || !input.trim()}>
          전송
        </button>
      </div>
    </div>
  );
}
