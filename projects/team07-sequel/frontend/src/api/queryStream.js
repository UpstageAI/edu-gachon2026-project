/**
 * 백엔드 POST /api/query 를 호출하고, SSE(text/event-stream) 응답을
 * 이벤트 단위로 잘라 콜백에 전달한다.
 *
 * teammate의 aiagent 포맷(docs/api.md)에 맞춘 형식이라, SSE 표준의
 * `event:` 줄은 쓰지 않는다. 매 청크가 `data: <JSON>\n\n` 한 줄뿐이고,
 * 그 JSON 안의 "event" 키가 종류(node/done/error)를 나타낸다.
 *
 * 브라우저 기본 EventSource는 GET만 지원해서 body를 못 보내기 때문에,
 * fetch + ReadableStream으로 직접 SSE 프레이밍을 파싱한다.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8080";

function parseSSEBlock(block) {
  const dataLines = [];

  for (const line of block.split("\n")) {
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  const dataStr = dataLines.join("\n");
  if (!dataStr) return null;

  try {
    const payload = JSON.parse(dataStr);
    return { type: payload.event, payload };
  } catch {
    return null;
  }
}

export async function streamQuery({ question, sessionId, onEvent, signal }) {
  const res = await fetch(`${BASE_URL}/api/query`, {
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

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      const event = parseSSEBlock(rawEvent);
      if (event) onEvent(event);

      boundary = buffer.indexOf("\n\n");
    }
  }
}
