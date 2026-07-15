import { pickCannedAnswer } from './askTui';

export type StreamHandler = (textSoFar: string) => void;

export interface VoiceQueryContext {
  recipeId: string;
  allergenIds: string[];
  currentStepText?: string;
}

export async function askTuiStream(
  question: string,
  context: VoiceQueryContext,
  onChunk: StreamHandler,
): Promise<string> {
  const endpoint = import.meta.env.VITE_TUI_ASK_ENDPOINT;
  if (!endpoint) {
    console.warn(
      'VITE_TUI_ASK_ENDPOINT가 설정되지 않아 실제 백엔드 대신 목업 답변을 사용합니다.',
    );
    return mockStream(question, onChunk);
  }
  return realAsk(endpoint, question, context, onChunk);
}

async function realAsk(
  endpoint: string,
  question: string,
  context: VoiceQueryContext,
  onChunk: StreamHandler,
): Promise<string> {
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      recipe_id: context.recipeId,
      allergen_ids: context.allergenIds,
      question,
      current_step_text: context.currentStepText,
    }),
  });

  if (!response.ok || !response.body) {
    throw new Error(`답변을 가져오지 못했어요 (${response.status})`);
  }

  return readSseStream(response.body, onChunk);
}

async function readSseStream(body: ReadableStream<Uint8Array>, onChunk: StreamHandler): Promise<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let answer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const events = buffer.split('\n\n');
    buffer = events.pop() ?? '';

    for (const rawEvent of events) {
      const dataLine = rawEvent.split('\n').find((line) => line.startsWith('data: '));
      if (!dataLine) continue;

      const payload = JSON.parse(dataLine.slice('data: '.length));
      if (typeof payload.answer === 'string') {
        answer = payload.answer;
        onChunk(answer);
      }
    }
  }

  return answer;
}

function mockStream(question: string, onChunk: StreamHandler): Promise<string> {
  const answer = pickCannedAnswer(question);
  return new Promise((resolve) => {
    let index = 0;
    const timer = setInterval(() => {
      index += 1;
      onChunk(answer.slice(0, index));
      if (index >= answer.length) {
        clearInterval(timer);
        resolve(answer);
      }
    }, 35);
  });
}
