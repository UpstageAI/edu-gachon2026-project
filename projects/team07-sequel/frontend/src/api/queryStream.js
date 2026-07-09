/**
 * 백엔드 POST /api/query 를 호출하고, SSE(text/event-stream) 응답을
 * 이벤트 단위로 잘라 콜백에 전달한다.
 *
 * 브라우저 기본 EventSource는 GET만 지원해서 body를 못 보내기 때문에,
 * fetch + ReadableStream으로 직접 SSE 프레이밍을 파싱한다.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8080";

function parseSSEBlock(block) {
  let eventType = "message";
  const dataLines = [];

  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) {
      eventType = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  const dataStr = dataLines.join("\n");
  if (!dataStr) return null;

  try {
    return { type: eventType, data: JSON.parse(dataStr) };
  } catch {
    return { type: eventType, data: dataStr };
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
