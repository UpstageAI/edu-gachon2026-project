import { useState, useRef, useEffect } from "react"
import type { Chat, Message, RecommendationFeedback } from "./types"
import { WELCOME_MESSAGE } from "./data"
import { streamChat, submitFeedback, toPolicyCard } from "./lib/api"
import {
  clearProfileDefaults,
  detectSensitiveData,
  loadChatState,
  loadProfileDefaults,
  privacyGuardMessage,
  sanitizeStoredText,
  saveChatState,
  saveProfileDefaults,
} from "./lib/chatStorage"
import Sidebar from "./components/Sidebar"
import ChatMessage from "./components/ChatMessage"
import ChatInput from "./components/ChatInput"

function generateId() {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  )
}

function generateTitle(text: string): string {
  return text.slice(0, 28) + (text.length > 28 ? "..." : "")
}

function buildWelcomeChat(): Chat {
  return {
    id: generateId(),
    title: "새 채팅",
    messages: [
      {
        id: generateId(),
        role: "assistant",
        content: WELCOME_MESSAGE,
        timestamp: new Date(),
      },
    ],
    createdAt: new Date(),
  }
}

export default function App() {
  const [initialChatState] = useState(() => {
    const restored = loadChatState()
    if (restored) return restored
    const first = buildWelcomeChat()
    return { chats: [first], activeChatId: first.id }
  })
  const [chats, setChats] = useState<Chat[]>(initialChatState.chats)
  const [activeChatId, setActiveChatId] = useState<string | null>(
    initialChatState.activeChatId,
  )
  const [isTyping, setIsTyping] = useState(false)
  const [typingStatus, setTypingStatus] = useState("질문을 확인하고 있어요.")
  const [profileDefaults, setProfileDefaults] = useState(() =>
    loadProfileDefaults(),
  )
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const chatStateRef = useRef({
    chats: initialChatState.chats,
    activeChatId: initialChatState.activeChatId,
  })

  const activeChat = chats.find((c) => c.id === activeChatId) ?? null

  useEffect(() => {
    chatStateRef.current = { chats, activeChatId }
    const timer = window.setTimeout(() => {
      saveChatState(chatStateRef.current)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [chats, activeChatId])

  useEffect(() => {
    const flushChatState = () => saveChatState(chatStateRef.current)
    window.addEventListener("pagehide", flushChatState)
    return () => window.removeEventListener("pagehide", flushChatState)
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [activeChat?.messages, isTyping])

  const handleNewChat = () => {
    const newChat = buildWelcomeChat()
    setChats((prev) => [newChat, ...prev])
    setActiveChatId(newChat.id)
  }

  const handleDeleteChat = (chatId: string) => {
    const remaining = chats.filter((chat) => chat.id !== chatId)
    setChats(remaining)
    if (activeChatId === chatId) {
      setActiveChatId(remaining[0]?.id ?? null)
    }
  }

  const handleClearChats = () => {
    if (
      !window.confirm(
        "모든 로컬 채팅 기록을 삭제할까요? 이 작업은 되돌릴 수 없습니다.",
      )
    )
      return
    setChats([])
    setActiveChatId(null)
    clearProfileDefaults()
    setProfileDefaults({})
  }

  const handleSend = async (text: string) => {
    if (!activeChatId) return
    // 채팅(Chat.id)을 백엔드 세션(LangGraph thread_id)으로 그대로 재사용해,
    // 같은 대화 안에서 프로필(지역/취업상태 등)이 누적되도록 한다.
    const sessionId = activeChatId
    const detectedSensitiveData = detectSensitiveData(text)
    const displayText =
      detectedSensitiveData.length > 0 ? sanitizeStoredText(text) : text

    const userMsg: Message = {
      id: generateId(),
      role: "user",
      content: displayText,
      timestamp: new Date(),
    }

    setChats((prev) =>
      prev.map((c) => {
        if (c.id !== activeChatId) return c
        const isFirst = c.messages.filter((m) => m.role === "user").length === 0
        return {
          ...c,
          title: isFirst ? generateTitle(displayText) : c.title,
          messages: [...c.messages, userMsg],
        }
      }),
    )

    if (detectedSensitiveData.length > 0) {
      const privacyReply: Message = {
        id: generateId(),
        role: "assistant",
        content: privacyGuardMessage(detectedSensitiveData),
        timestamp: new Date(),
      }
      setChats((prev) =>
        prev.map((chat) =>
          chat.id === activeChatId
            ? { ...chat, messages: [...chat.messages, privacyReply] }
            : chat,
        ),
      )
      return
    }

    setIsTyping(true)
    setTypingStatus("질문을 확인하고 있어요.")

    const assistantId = generateId()

    const appendToken = (chunk: string) => {
      setChats((prev) =>
        prev.map((c) => {
          if (c.id !== activeChatId) return c
          const exists = c.messages.some((m) => m.id === assistantId)
          if (!exists) {
            const aiMsg: Message = {
              id: assistantId,
              role: "assistant",
              content: chunk,
              timestamp: new Date(),
            }
            return { ...c, messages: [...c.messages, aiMsg] }
          }
          return {
            ...c,
            messages: c.messages.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + chunk } : m,
            ),
          }
        }),
      )
      setIsTyping(false)
    }

    try {
      const result = await streamChat(
        sessionId,
        text,
        appendToken,
        setTypingStatus,
        profileDefaults,
      )
      const nextProfileDefaults = {
        ...profileDefaults,
        ...result.profileDefaults,
      }
      setProfileDefaults(nextProfileDefaults)
      saveProfileDefaults(nextProfileDefaults)
      const cards = result.recommendations.map(toPolicyCard)

      if (cards.length > 0) {
        setChats((prev) =>
          prev.map((c) =>
            c.id === activeChatId
              ? {
                  ...c,
                  messages: c.messages.map((m) =>
                    m.id === assistantId
                      ? { ...m, policyCards: cards, traceId: result.traceId }
                      : m,
                  ),
                }
              : c,
          ),
        )
      }
    } catch {
      setChats((prev) =>
        prev.map((c) =>
          c.id === activeChatId
            ? {
                ...c,
                messages: [
                  ...c.messages,
                  {
                    id: generateId(),
                    role: "assistant",
                    content:
                      "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.",
                    timestamp: new Date(),
                  },
                ],
              }
            : c,
        ),
      )
    } finally {
      setIsTyping(false)
      setTypingStatus("질문을 확인하고 있어요.")
    }
  }

  const handleFeedback = (messageId: string, rating: RecommendationFeedback) => {
    if (!activeChatId) return
    const message = activeChat?.messages.find((m) => m.id === messageId)

    setChats((prev) =>
      prev.map((c) =>
        c.id === activeChatId
          ? {
              ...c,
              messages: c.messages.map((m) =>
                m.id === messageId ? { ...m, feedback: rating } : m,
              ),
            }
          : c,
      ),
    )

    submitFeedback(activeChatId, messageId, message?.traceId ?? null, rating)
  }

  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        background: "#f7f8fb",
        overflow: "hidden",
      }}
    >
      {/* Sidebar - always rendered, just width-toggled */}
      <div
        style={{
          width: sidebarOpen ? "260px" : "0px",
          minWidth: sidebarOpen ? "260px" : "0px",
          overflow: "hidden",
          transition: "width 0.25s ease, min-width 0.25s ease",
          flexShrink: 0,
        }}
      >
        <Sidebar
          chats={chats}
          activeChatId={activeChatId}
          onSelectChat={(id) => {
            setActiveChatId(id)
          }}
          onNewChat={handleNewChat}
          onDeleteChat={handleDeleteChat}
          onClearChats={handleClearChats}
          isOpen={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
        />
      </div>

      {/* Main */}
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          minWidth: 0,
          height: "100%",
        }}
      >
        {/* Top bar */}
        <header
          style={{
            height: "52px",
            borderBottom: "1px solid #e2e5ec",
            display: "flex",
            alignItems: "center",
            padding: "0 20px",
            background: "#f7f8fb",
            flexShrink: 0,
            gap: "12px",
          }}
        >
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            style={{
              background: "transparent",
              border: "none",
              color: "#6b7280",
              cursor: "pointer",
              padding: "6px 8px",
              borderRadius: "6px",
              fontSize: "17px",
              lineHeight: 1,
              transition: "color 0.15s, background 0.15s",
            }}
            onMouseEnter={(e) => {
              ;(e.currentTarget as HTMLButtonElement).style.color = "#1f2430"
              ;(e.currentTarget as HTMLButtonElement).style.background =
                "#eef1f7"
            }}
            onMouseLeave={(e) => {
              ;(e.currentTarget as HTMLButtonElement).style.color = "#6b7280"
              ;(e.currentTarget as HTMLButtonElement).style.background =
                "transparent"
            }}
            title="사이드바 토글"
          >
            ☰
          </button>

          {!sidebarOpen && (
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <div
                style={{
                  width: "24px",
                  height: "24px",
                  borderRadius: "6px",
                  background: "linear-gradient(135deg, #4f7ef8, #38c96e)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "13px",
                }}
              >
                🧭
              </div>
              <span
                style={{ fontSize: "14px", fontWeight: 700, color: "#1f2430" }}
              >
                정책나침반
              </span>
            </div>
          )}

          <div
            style={{
              flex: 1,
              fontSize: "13.5px",
              color: "#6b7280",
              fontWeight: 500,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {activeChat?.title ?? ""}
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              background: "#eef1f7",
              border: "1px solid #e2e5ec",
              borderRadius: "999px",
              padding: "4px 12px",
              fontSize: "11.5px",
              color: "#1f9d54",
              fontWeight: 600,
              flexShrink: 0,
            }}
          >
            <span
              style={{
                width: "6px",
                height: "6px",
                borderRadius: "50%",
                background: "#1f9d54",
                display: "inline-block",
                boxShadow: "0 0 6px #1f9d5480",
              }}
            />
            실시간 연동
          </div>
        </header>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: "auto", padding: "28px 20px" }}>
          <div
            style={{
              maxWidth: "780px",
              margin: "0 auto",
              display: "flex",
              flexDirection: "column",
              gap: "20px",
            }}
          >
            {activeChat ? (
              activeChat.messages.map((msg) => (
                <ChatMessage key={msg.id} message={msg} onFeedback={handleFeedback} />
              ))
            ) : (
              <div
                style={{
                  textAlign: "center",
                  color: "#8a90a3",
                  marginTop: "80px",
                }}
              >
                <div style={{ fontSize: "40px", marginBottom: "16px" }}>🧭</div>
                <div
                  style={{
                    fontSize: "18px",
                    fontWeight: 700,
                    color: "#1f2430",
                    marginBottom: "8px",
                  }}
                >
                  정책나침반과 대화를 시작해보세요
                </div>
                <div style={{ fontSize: "14px", color: "#6b7280" }}>
                  왼쪽에서 채팅을 선택하거나 새 채팅을 시작하세요
                </div>
              </div>
            )}

            {/* Typing indicator */}
            {isTyping && (
              <div
                className="msg-appear"
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "flex-start",
                  gap: "4px",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    paddingLeft: "4px",
                  }}
                >
                  <div
                    style={{
                      width: "22px",
                      height: "22px",
                      borderRadius: "6px",
                      background: "linear-gradient(135deg, #4f7ef8, #38c96e)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: "11px",
                    }}
                  >
                    🧭
                  </div>
                  <span
                    style={{
                      fontSize: "11.5px",
                      color: "#6b7280",
                      fontWeight: 600,
                    }}
                  >
                    정책나침반
                  </span>
                </div>
                <div
                  style={{
                    background: "#ffffff",
                    border: "1px solid #e2e5ec",
                    borderRadius: "4px 16px 16px 16px",
                    padding: "14px 18px",
                    display: "flex",
                    gap: "8px",
                    alignItems: "center",
                  }}
                >
                  <span style={{ fontSize: "13px", color: "#6b7280" }}>
                    {typingStatus}
                  </span>
                  <span
                    className="typing-dot"
                    style={{
                      width: "7px",
                      height: "7px",
                      borderRadius: "50%",
                      background: "#9aa0b4",
                      display: "inline-block",
                    }}
                  />
                  <span
                    className="typing-dot"
                    style={{
                      width: "7px",
                      height: "7px",
                      borderRadius: "50%",
                      background: "#9aa0b4",
                      display: "inline-block",
                    }}
                  />
                  <span
                    className="typing-dot"
                    style={{
                      width: "7px",
                      height: "7px",
                      borderRadius: "50%",
                      background: "#9aa0b4",
                      display: "inline-block",
                    }}
                  />
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Input */}
        {activeChat && <ChatInput onSend={handleSend} disabled={isTyping} />}

        {/* No chat selected: show new chat prompt */}
        {!activeChat && (
          <div
            style={{
              padding: "20px",
              borderTop: "1px solid #e2e5ec",
              textAlign: "center",
            }}
          >
            <button
              onClick={handleNewChat}
              style={{
                background: "#4f7ef8",
                color: "#fff",
                border: "none",
                borderRadius: "10px",
                padding: "12px 28px",
                fontSize: "14px",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              새 채팅 시작하기
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
