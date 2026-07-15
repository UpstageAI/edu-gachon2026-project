import type { ChatStreamRequest, StreamEvent } from "../types/chat";
import { buildApiUrl } from "./apiClient";
import { parseSseChunk } from "./sseParser";

const decoder = new TextDecoder();

export async function* streamChatResponse(
  request: ChatStreamRequest,
): AsyncGenerator<StreamEvent> {
  const response = await fetch(buildApiUrl("/chat/stream"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message: request.message,
      question: request.message,
      query: request.message,
      thread_id: request.threadId,
    }),
  });

  if (!response.ok || !response.body) {
    yield {
      type: "error",
      content: "백엔드 스트리밍 응답을 받을 수 없습니다.",
      status: `HTTP ${response.status}`,
    };
    return;
  }

  const reader = response.body.getReader();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();

    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lastEventBoundary = buffer.lastIndexOf("\n\n");

    if (lastEventBoundary === -1) continue;

    const completeChunk = buffer.slice(0, lastEventBoundary + 2);
    buffer = buffer.slice(lastEventBoundary + 2);

    for (const event of parseSseChunk(completeChunk)) {
      yield event;
    }
  }

  if (buffer.trim()) {
    for (const event of parseSseChunk(`${buffer}\n\n`)) {
      yield event;
    }
  }
}
