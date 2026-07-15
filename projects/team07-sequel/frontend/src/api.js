/**
 * 백엔드(FastAPI, /api/v1) 호출 래퍼.
 *
 * - streamQuery: POST /query/stream 을 fetch+ReadableStream 으로 SSE 파싱.
 *   백엔드 실제 계약: 각 SSE 블록의 data 라인 = StreamEvent JSON
 *   {event:"node"|"done"|"error", node, data:"<inner JSON string>"}.
 *   (EventSource 는 GET 전용이라 body 를 못 실어 직접 파싱)
 * - fetchSuggestions: POST /suggestions (직전 성공 턴 기반 후속질문 0~2개)
 * - fetchMetrics: GET /metrics (Home 대시보드 KPI, Langfuse 집계 프록시)
 */
const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const V1 = `${BASE}/api/v1`;

// 노드명 → 진행 상태 한글 문구 (Ask 화면의 "SQL 생성 중…" 실시간 표시)
const NODE_LABEL = {
  normalize: "질문을 이해하는 중…",
  schema_link: "스키마를 탐색하는 중…",
  route: "난이도를 분석하는 중…",
  generate: "SQL을 생성하는 중…",
  validate: "쿼리를 검증하는 중…",
  execute: "데이터를 조회하는 중…",
  format: "답변을 작성하는 중…",
};

function parseSSEBlock(block) {
  const dataLines = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  const raw = dataLines.join("\n");
  if (!raw) return null;
  try {
    return JSON.parse(raw); // StreamEvent {event,node,data}
  } catch {
    return null;
  }
}

function safeParse(s) {
  try {
    return JSON.parse(s);
  } catch {
    return {};
  }
}

/**
 * onEvent 로 구조화된 이벤트를 흘려보낸다:
 *   {type:"status", label}          진행 중 노드 문구
 *   {type:"route", difficulty, model}
 *   {type:"done", answer}           최종 {summary, table:{columns,rows}, sql, meta}
 *   {type:"error", message}
 */
export async function streamQuery({ question, sessionId, onEvent, signal }) {
  const res = await fetch(`${V1}/query/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, session_id: sessionId }),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`서버 응답 오류 (status ${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let i = buffer.indexOf("\n\n");
    while (i !== -1) {
      const ev = parseSSEBlock(buffer.slice(0, i));
      buffer = buffer.slice(i + 2);
      if (ev) dispatch(ev, onEvent);
      i = buffer.indexOf("\n\n");
    }
  }
}

function dispatch(ev, onEvent) {
  if (ev.event === "node") {
    const slice = safeParse(ev.data);
    if (ev.node === "route") {
      onEvent({ type: "route", difficulty: slice.difficulty, model: slice.model });
    } else if (ev.node === "schema_link" && Array.isArray(slice.tables)) {
      onEvent({ type: "tables", tables: slice.tables });
    }
    onEvent({ type: "status", label: NODE_LABEL[ev.node] || "처리 중…" });
  } else if (ev.event === "done") {
    onEvent({ type: "done", answer: safeParse(ev.data) });
  } else if (ev.event === "error") {
    onEvent({ type: "error", message: ev.data || "오류가 발생했습니다." });
  }
}

export async function fetchSuggestions(sessionId) {
  try {
    const res = await fetch(`${V1}/suggestions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (!res.ok) return [];
    const j = await res.json();
    return Array.isArray(j.suggestions) ? j.suggestions : [];
  } catch {
    return [];
  }
}

export async function fetchMetrics() {
  try {
    const res = await fetch(`${V1}/metrics`);
    if (!res.ok) return { kpis: [], as_of: "", available: false };
    return await res.json();
  } catch {
    return { kpis: [], as_of: "", available: false };
  }
}

// GET /schema — 스키마 브라우저용 {tables:[{name, columns:[{name,type}]}]}.
// 스키마는 거의 안 변하니 성공 응답만 페이지 로드당 1회 캐시.
let _schemaCache = null;
export async function fetchSchema() {
  if (_schemaCache) return _schemaCache;
  try {
    const res = await fetch(`${V1}/schema`);
    if (!res.ok) return { tables: [] };
    _schemaCache = await res.json();
    return _schemaCache;
  } catch {
    return { tables: [] };
  }
}
