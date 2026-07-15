import type { Chat, Message, PolicyCard } from "../types"
import type { UserProfileDefaults } from "./api"

export const CHAT_STORAGE_KEY = "policy-compass.chat-state.v1"
export const PROFILE_DEFAULTS_STORAGE_KEY = "policy-compass.profile-defaults.v1"

const STORAGE_VERSION = 1
const MAX_CHATS = 20
const MAX_MESSAGES_PER_CHAT = 50
const MAX_POLICY_CARDS_PER_MESSAGE = 10
const MAX_MESSAGE_LENGTH = 4000
const MAX_TITLE_LENGTH = 120
const SAFE_ID = /^[A-Za-z0-9_-]{1,128}$/
const SENSITIVE_PATTERNS = [
  {
    label: "주민등록번호·외국인등록번호 형태",
    pattern: /(?<!\d)\d{6}\s*-?\s*[1-8]\d{6}(?!\d)/g,
  },
  {
    label: "전화번호 형태",
    pattern: /(?<!\d)(?:\+82[ -]?)?0?1[016789][ -]?\d{3,4}[ -]?\d{4}(?!\d)/g,
  },
  {
    label: "이메일 주소",
    pattern: /(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?![\w.-])/g,
  },
  {
    label: "계좌번호 형태",
    pattern: /(?:계좌(?:번호)?|통장번호)\s*[:：]?\s*(?:\d[ -]?){8,20}/g,
  },
  {
    label: "카드·금융번호 형태",
    pattern: /(?<!\d)(?:\d[ -]?){13,19}(?!\d)/g,
  },
]

export interface ChatState {
  chats: Chat[]
  activeChatId: string | null
}

interface PersistedMessage extends Omit<Message, "timestamp"> {
  timestamp: string
}

interface PersistedChat extends Omit<Chat, "messages" | "createdAt"> {
  messages: PersistedMessage[]
  createdAt: string
}

interface PersistedChatState {
  version: typeof STORAGE_VERSION
  chats: PersistedChat[]
  activeChatId: string | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function safeId(value: unknown): string | null {
  return typeof value === "string" && SAFE_ID.test(value) ? value : null
}

export function sanitizeStoredText(
  value: string,
  maxLength = MAX_MESSAGE_LENGTH,
): string {
  let sanitized = value.slice(0, maxLength)
  for (const item of SENSITIVE_PATTERNS) {
    sanitized = sanitized.replace(item.pattern, "[민감정보 삭제]")
  }
  return sanitized
}

export function detectSensitiveData(value: string): string[] {
  const detected: string[] = []
  let remaining = value
  for (const item of SENSITIVE_PATTERNS) {
    item.pattern.lastIndex = 0
    if (!item.pattern.test(remaining)) continue
    detected.push(item.label)
    remaining = remaining.replace(item.pattern, "[민감정보 삭제]")
  }
  return detected
}

export function privacyGuardMessage(detectedLabels: string[]): string {
  const labels = detectedLabels.join("·") || "민감 개인정보"
  return (
    `입력에서 민감 개인정보(${labels})를 감지해 전송과 정책 검색을 중단했어요. ` +
    "입력 내용은 화면과 로컬 기록에서 삭제 표식으로 바꿨어요. " +
    "정책 추천에는 주민등록번호·연락처·계좌번호가 필요하지 않아요. " +
    "만 나이, 거주 시·도, 취업 또는 창업 상태처럼 필요한 조건만 알려주세요."
  )
}

function safeString(value: unknown): string | null {
  return typeof value === "string" ? value : null
}

function parseDate(value: unknown): Date | null {
  if (typeof value !== "string") return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function parsePolicyCard(value: unknown): PolicyCard | null {
  if (!isRecord(value)) return null

  const id = safeString(value.id)
  const name = safeString(value.name)
  const target = safeString(value.target)
  const amount = safeString(value.amount)
  const period = safeString(value.period)
  const reason = safeString(value.reason)
  const ministry = safeString(value.ministry)
  const category = safeString(value.category)
  const region = safeString(value.region) ?? "지역 확인 필요"
  const scope = [
    "exact",
    "nationwide",
    "nearby_reference",
    "excluded",
  ].includes(String(value.scope))
    ? value.scope as PolicyCard["scope"]
    : "exact"
  const distanceKm =
    typeof value.distanceKm === "number" ? value.distanceKm : null
  const matchScore =
    typeof value.matchScore === "number"
      ? Math.min(Math.max(value.matchScore, 0), 1)
      : undefined
  const evidenceCoverage =
    typeof value.evidenceCoverage === "number"
      ? Math.min(Math.max(value.evidenceCoverage, 0), 1)
      : undefined
  const url = value.url === undefined ? undefined : safeString(value.url)

  if (
    !id ||
    !name ||
    target === null ||
    amount === null ||
    period === null ||
    reason === null ||
    !ministry ||
    !category
  ) {
    return null
  }

  return {
    id,
    name,
    target,
    amount,
    period,
    reason,
    ministry,
    category,
    region,
    scope,
    distanceKm,
    ...(matchScore !== undefined ? { matchScore } : {}),
    ...(evidenceCoverage !== undefined ? { evidenceCoverage } : {}),
    ...(url ? { url } : {}),
  }
}

function parseMessage(value: unknown): Message | null {
  if (!isRecord(value)) return null

  const id = safeId(value.id)
  const role = value.role
  const content = safeString(value.content)
  const timestamp = parseDate(value.timestamp)
  if (
    !id ||
    (role !== "user" && role !== "assistant") ||
    content === null ||
    !timestamp
  ) {
    return null
  }

  const policyCards = Array.isArray(value.policyCards)
    ? value.policyCards
        .slice(0, MAX_POLICY_CARDS_PER_MESSAGE)
        .map(parsePolicyCard)
        .filter((card): card is PolicyCard => card !== null)
    : undefined

  const traceId = safeString(value.traceId)
  const feedback =
    value.feedback === "up" || value.feedback === "down" ? value.feedback : undefined

  return {
    id,
    role,
    content,
    timestamp,
    ...(policyCards && policyCards.length > 0 ? { policyCards } : {}),
    ...(traceId ? { traceId } : {}),
    ...(feedback ? { feedback } : {}),
  }
}

function parseChat(value: unknown): Chat | null {
  if (!isRecord(value) || !Array.isArray(value.messages)) return null

  const id = safeId(value.id)
  const title = safeString(value.title)
  const createdAt = parseDate(value.createdAt)
  if (!id || title === null || !createdAt) return null

  const messages = value.messages
    .slice(-MAX_MESSAGES_PER_CHAT)
    .map(parseMessage)
    .filter((message): message is Message => message !== null)

  return { id, title, messages, createdAt }
}

function sanitizePolicyCard(card: PolicyCard): PolicyCard {
  return {
    ...card,
    name: sanitizeStoredText(card.name),
    target: sanitizeStoredText(card.target),
    amount: sanitizeStoredText(card.amount),
    period: sanitizeStoredText(card.period),
    reason: sanitizeStoredText(card.reason),
    ministry: sanitizeStoredText(card.ministry),
    category: sanitizeStoredText(card.category),
    region: sanitizeStoredText(card.region),
  }
}

function serializeMessage(message: Message): PersistedMessage {
  return {
    ...message,
    content: sanitizeStoredText(message.content),
    timestamp: message.timestamp.toISOString(),
    ...(message.policyCards
      ? {
          policyCards: message.policyCards
            .slice(0, MAX_POLICY_CARDS_PER_MESSAGE)
            .map(sanitizePolicyCard),
        }
      : {}),
  }
}

function serializeChat(chat: Chat): PersistedChat {
  return {
    id: chat.id,
    title: sanitizeStoredText(chat.title, MAX_TITLE_LENGTH),
    messages: chat.messages.slice(-MAX_MESSAGES_PER_CHAT).map(serializeMessage),
    createdAt: chat.createdAt.toISOString(),
  }
}

export function loadChatState(): ChatState | null {
  if (typeof window === "undefined") return null

  try {
    const stored = window.localStorage.getItem(CHAT_STORAGE_KEY)
    if (!stored) return null

    const raw: unknown = JSON.parse(stored)
    if (
      !isRecord(raw) ||
      raw.version !== STORAGE_VERSION ||
      !Array.isArray(raw.chats)
    ) {
      return null
    }

    const chats = raw.chats
      .slice(0, MAX_CHATS)
      .map(parseChat)
      .filter((chat): chat is Chat => chat !== null)
    const requestedActiveId = safeId(raw.activeChatId)
    const activeChatId = chats.some((chat) => chat.id === requestedActiveId)
      ? requestedActiveId
      : (chats[0]?.id ?? null)

    return { chats, activeChatId }
  } catch {
    return null
  }
}

export function saveChatState(state: ChatState): void {
  if (typeof window === "undefined") return

  try {
    const chats = state.chats.slice(0, MAX_CHATS).map(serializeChat)
    const activeChatId = chats.some((chat) => chat.id === state.activeChatId)
      ? state.activeChatId
      : (chats[0]?.id ?? null)
    const persisted: PersistedChatState = {
      version: STORAGE_VERSION,
      chats,
      activeChatId,
    }
    window.localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(persisted))
  } catch {
    // 저장소 차단·용량 초과 시 현재 탭의 메모리 채팅은 계속 동작한다.
  }
}

export function loadProfileDefaults(): UserProfileDefaults {
  if (typeof window === "undefined") return {}

  try {
    const stored = window.localStorage.getItem(PROFILE_DEFAULTS_STORAGE_KEY)
    if (!stored) return {}
    const raw: unknown = JSON.parse(stored)
    if (!isRecord(raw)) return {}

    const age =
      typeof raw.age === "number" &&
      Number.isInteger(raw.age) &&
      raw.age >= 0 &&
      raw.age <= 120
        ? raw.age
        : undefined
    const region =
      typeof raw.region === "string" && raw.region.trim().length > 0
        ? sanitizeStoredText(raw.region.trim(), 100)
        : undefined
    return {
      ...(age !== undefined ? { age } : {}),
      ...(region !== undefined ? { region } : {}),
    }
  } catch {
    return {}
  }
}

export function saveProfileDefaults(profile: UserProfileDefaults): void {
  if (typeof window === "undefined") return

  try {
    const safeProfile: UserProfileDefaults = {
      ...(typeof profile.age === "number" &&
      Number.isInteger(profile.age) &&
      profile.age >= 0 &&
      profile.age <= 120
        ? { age: profile.age }
        : {}),
      ...(typeof profile.region === "string" && profile.region.trim().length > 0
        ? { region: sanitizeStoredText(profile.region.trim(), 100) }
        : {}),
    }
    window.localStorage.setItem(
      PROFILE_DEFAULTS_STORAGE_KEY,
      JSON.stringify(safeProfile),
    )
  } catch {
    // 저장소 차단·용량 초과 시 채팅 자체는 계속 동작한다.
  }
}

export function clearProfileDefaults(): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.removeItem(PROFILE_DEFAULTS_STORAGE_KEY)
  } catch {
    // 저장소가 차단된 경우에도 전체 기록 삭제 흐름을 막지 않는다.
  }
}
