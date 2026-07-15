import type { PolicyCard } from "../types"

// FastAPI 백엔드(app/schemas/policy.py의 PolicyItem)를 그대로 반영한 타입.
export interface BackendPolicy {
  id: string
  title: string
  agency: string
  category: string
  target_description: string
  region: string[]
  min_age: number | null
  max_age: number | null
  apply_start: string | null
  apply_end: string | null
  apply_method: string
  support_content: string
  source_url: string
  match_scope: "exact" | "nationwide" | "nearby" | "unknown"
  distance_km: number | null
}

// app/graph/scoring.py의 score_policy() 반환 형태(scored_results 항목).
export interface BackendRecommendation {
  policy: BackendPolicy
  match_score: number
  evidence_coverage: number
  match_reasons: string[]
  follow_up_checks: string[]
  is_recommendable: boolean
  recommendation_scope: "exact" | "nationwide" | "nearby_reference" | "excluded"
  deadline_status: string
}

export interface UserProfileDefaults {
  age?: number
  region?: string
}

export interface ChatStreamResult {
  intent: string
  missingSlots: string[]
  recommendations: BackendRecommendation[]
  profileDefaults: UserProfileDefaults
  traceId: string | null
}

type TokenHandler = (chunk: string) => void
type StatusHandler = (message: string) => void

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ""

/**
 * POST /api/chat/stream 을 호출해 SSE(event: token / event: done / event: error)를
 * 파싱한다. 토큰이 도착할 때마다 onToken을 호출하고, 스트림이 끝나면
 * intent/missing_slots/recommendations를 담은 최종 결과를 반환한다.
 */
export async function streamChat(
  sessionId: string,
  message: string,
  onToken: TokenHandler,
  onStatus?: StatusHandler,
  profileDefaults: UserProfileDefaults = {},
): Promise<ChatStreamResult> {
  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      message,
      profile_defaults: profileDefaults,
    }),
  })

  if (!res.ok || !res.body) {
    throw new Error(`채팅 서버 오류가 발생했어요 (status ${res.status}).`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let result: ChatStreamResult = {
    intent: "GENERAL",
    missingSlots: [],
    recommendations: [],
    profileDefaults,
    traceId: null,
  }

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const events = buffer.split("\n\n")
    buffer = events.pop() ?? ""

    for (const raw of events) {
      const dataLine = raw.split("\n").find((line) => line.startsWith("data:"))
      if (!dataLine) continue

      const payload = JSON.parse(dataLine.slice(5).trim())

      if (payload.type === "token") {
        onToken(payload.content as string)
      } else if (payload.type === "status") {
        onStatus?.(payload.message as string)
      } else if (payload.type === "done") {
        result = {
          intent: payload.intent,
          missingSlots: payload.missing_slots ?? [],
          recommendations: payload.recommendations ?? [],
          profileDefaults: payload.profile_defaults ?? profileDefaults,
          traceId: payload.trace_id ?? null,
        }
      } else if (payload.type === "error") {
        throw new Error(payload.message ?? "알 수 없는 오류가 발생했어요.")
      }
    }
  }

  return result
}

/** 백엔드 추천 결과(BackendRecommendation)를 프론트엔드 PolicyCard로 매핑한다. */
export function toPolicyCard(rec: BackendRecommendation): PolicyCard {
  const { policy } = rec
  return {
    id: policy.id,
    name: policy.title,
    target: policy.target_description,
    amount: policy.support_content,
    period: `${policy.apply_start ?? "상시"} ~ ${policy.apply_end ?? "상시"}`,
    reason: rec.match_reasons.join(" "),
    ministry: policy.agency,
    category: policy.category,
    url: policy.source_url,
    region: policy.region.join(", ") || "지역 확인 필요",
    scope: rec.recommendation_scope,
    distanceKm: policy.distance_km,
    matchScore: rec.match_score,
    evidenceCoverage: rec.evidence_coverage,
  }
}

/** 추천 결과(말풍선 1개)에 대한 엄지 업/다운 피드백을 백엔드로 전송한다. */
export async function submitFeedback(
  sessionId: string,
  messageId: string,
  traceId: string | null,
  rating: "up" | "down",
): Promise<void> {
  await fetch(`${API_BASE}/api/chat/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      message_id: messageId,
      trace_id: traceId,
      rating,
    }),
  })
}
