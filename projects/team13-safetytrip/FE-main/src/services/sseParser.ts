import type { StreamEvent } from "../types/chat";

function toMessage(data: any, fallback: string) {
  return data?.message ?? data?.text ?? data?.detail ?? data?.reason ?? fallback;
}

function formatContact(data: any) {
  const agency = data?.contact?.agency;
  const phone = data?.contact?.phone;
  const message = toMessage(data, "");

  if (!agency && !phone) return "";
  if ((agency && message.includes(agency)) || (phone && message.includes(phone))) return "";
  if (agency && phone) return `\n\n문의 기관: ${agency} (${phone})`;
  return `\n\n문의 기관: ${agency ?? phone}`;
}

function normalizeBackendEvent(eventName: string, data: any): StreamEvent | null {
  switch (eventName) {
    case "session":
      return {
        type: "session",
        status: "대화 세션을 연결했습니다.",
        data,
      };

    case "token":
      return {
        type: "token",
        content: data?.text ?? data?.content ?? "",
      };

    case "parsed":
      return {
        type: "parsed",
        status: "질문에서 지역과 시기를 분석했습니다.",
        data,
      };

    case "stats":
      return {
        type: "stats",
        status: "재난 통계를 계산했습니다.",
        data,
      };

    case "citation":
      return {
        type: "citation",
        status: "공식 행동요령 출처를 확인했습니다.",
        data,
      };

    case "reask":
      return {
        type: "reask",
        content: toMessage(data, "지역과 시기를 조금 더 구체적으로 입력해 주세요."),
        data,
      };

    case "escalate":
      return {
        type: "escalate",
        content: `${toMessage(data, "공식 근거가 부족해 관련 기관 안내로 전환합니다.")}${formatContact(data)}`,
        status: data?.reason ?? "관련 기관 안내",
        data,
      };

    case "degraded":
      return {
        type: "degraded",
        content: `${toMessage(data, "AI 답변 생성이 어려워 공식 행동요령 원문 안내로 전환합니다.")}${formatContact(data)}`,
        status: data?.reason ?? "일부 기능 장애",
        data,
      };

    case "error":
      return {
        type: "error",
        content: `${toMessage(data, "일시적으로 AI 서비스에 연결할 수 없습니다.")}${formatContact(data)}`,
        data,
      };

    case "done":
      return { type: "done" };

    default:
      return null;
  }
}

function parseEventData(dataLines: string[]) {
  if (dataLines.length === 0) return {};

  const rawData = dataLines.join("\n");
  if (!rawData.trim()) return {};

  return JSON.parse(rawData);
}

export function parseSseChunk(chunk: string): StreamEvent[] {
  return chunk
    .split("\n\n")
    .map((eventText) => eventText.trim())
    .filter(Boolean)
    .map((eventText) => {
      const lines = eventText.split("\n");
      const eventName =
        lines
          .find((line) => line.startsWith("event:"))
          ?.slice(6)
          .trim() ?? "";
      const dataLines = lines
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim());

      const data = parseEventData(dataLines);

      if (eventName) {
        return normalizeBackendEvent(eventName, data);
      }

      return data as StreamEvent;
    })
    .filter((event): event is StreamEvent => event !== null);
}
