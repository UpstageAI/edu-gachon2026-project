import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'

import Aurora from './components/Aurora'
import AuthModal from './components/AuthModal'
import ChatPanel from './components/ChatPanel'
import NavBar from './components/NavBar'
import Sidebar from './components/Sidebar'
import StockPanel from './components/StockPanel'
import {
  bulkSaveConversations,
  deleteConversationRemote,
  fetchConversations,
  getToken,
  getUsername,
  loadDeletedConversationIds,
  loadConversations,
  markConversationDeleted,
  saveConversations,
  setAuth,
} from './lib/api'

const AURORA_COLORS = ['#052e21', '#34d399', '#065f46']
const ANALYSIS_HINT = '국내 상장 종목명(KOSPI/KOSDAQ)을 입력하면 등락 흐름과 근거를 분석해드려요. (예: 삼성전자)'
const SESSION_DOMAIN_HINTS = [
  '주식', '종목', '주가', '시세', '등락', '상승', '하락', '급등', '급락',
  '뉴스', '공시', 'dart', '재무', '실적', '매출', '영업이익', '순이익',
  '투자', '투자용어', '용어', '상장', 'ipo', '공모', '청약', '호재', '악재',
  '리스크', '사업보고서', '분기보고서', '보고서', 'per', 'pbr', 'eps', 'roe',
  '매수', '매도', '삼성전자', '삼전', 'sk하이닉스', '하이닉스', '한화오션',
  '셀트리온', '네이버', 'naver', '카카오', '현대차', '기아', 'lg', 'posco',
]

function deriveTitle(messages, fallback) {
  const firstUser = (messages || []).find((m) => m.role === 'user')
  if (firstUser && firstUser.text) return firstUser.text.slice(0, 24)
  return fallback || '새 대화'
}

function conversationTime(conversation, fallbackIndex = 0) {
  const value = conversation?.updatedAt || conversation?.createdAt || 0
  if (typeof value === 'number') return value
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? -fallbackIndex : parsed
}

function latestConversation(conversations) {
  const candidates = conversations.filter(hasConversationContent)
  if (!candidates.length) return null
  return candidates
    .map((conversation, index) => ({ conversation, index }))
    .sort((a, b) => conversationTime(b.conversation, b.index) - conversationTime(a.conversation, a.index))[0]
    .conversation
}

function hasConversationPayload(conversation) {
  return (
    (conversation?.messages || []).length > 0
    || (conversation?.insights || []).length > 0
  )
}

function hasDomainSignal(conversation) {
  if ((conversation?.insights || []).length > 0) return true

  const messages = conversation?.messages || []
  if (
    messages.some((message) =>
      message?.price
      || (message?.sources || []).length > 0
      || (message?.terms || []).length > 0
    )
  ) {
    return true
  }

  const userText = messages
    .filter((message) => message?.role === 'user')
    .map((message) => message?.text || '')
    .join(' ')
    .toLowerCase()
    .replace(/\s+/g, '')

  return SESSION_DOMAIN_HINTS.some((hint) => userText.includes(hint.toLowerCase().replace(/\s+/g, '')))
}

function hasConversationContent(conversation) {
  return (
    !conversation?.draft
    && hasConversationPayload(conversation)
    && hasDomainSignal(conversation)
  )
}

function createConversation({ draft = false } = {}) {
  const now = Date.now()
  return {
    id: 'c-' + now,
    sessionId: 'web-' + Math.random().toString(36).slice(2),
    title: '새 대화',
    messages: [],
    insights: [],
    favorite: false,
    createdAt: now,
    updatedAt: now,
    draft,
  }
}

function cleanServerConversations(list) {
  const deleted = loadDeletedConversationIds()
  const source = Array.isArray(list) ? list : []
  source
    .filter((conversation) =>
      conversation?.id
      && hasConversationPayload(conversation)
      && (!hasConversationContent(conversation) || deleted.has(conversation.id))
    )
    .forEach((conversation) => deleteConversationRemote(conversation.id).catch(() => {}))

  return source
    .filter(hasConversationContent)
    .filter((conversation) => !deleted.has(conversation.id))
}

function retryDeletedConversationDeletes() {
  const deletedIds = [...loadDeletedConversationIds()]
  if (!deletedIds.length || !getToken()) return
  Promise.allSettled(deletedIds.map((id) => deleteConversationRemote(id))).catch(() => {})
}

function App() {
  // 로그인 상태로 시작하면 서버에서 불러오므로 빈 배열, 게스트면 로컬에서 복원
  const [conversations, setConversations] = useState(() =>
    getToken() ? [] : loadConversations().filter(hasConversationContent)
  )
  const [activeId, setActiveId] = useState(null)
  const [started, setStarted] = useState(false)
  const [seed, setSeed] = useState(null)
  const [username, setUsername] = useState(() => getUsername() || null)
  const [showAuth, setShowAuth] = useState(false)
  const syncTimer = useRef(null)

  // 로그인 상태로 앱을 열면 서버의 내 대화를 불러온다.
  useEffect(() => {
    if (!getToken()) return
    fetchConversations()
      .then((list) => {
        retryDeletedConversationDeletes()
        const loaded = cleanServerConversations(list)
        if (loaded.length) {
          const pick = latestConversation(loaded)
          setConversations(loaded)
          setActiveId(pick.id)
          setStarted(true)
          setSeed(null)
        } else {
          const draft = createConversation({ draft: true })
          setConversations([draft])
          setActiveId(draft.id)
          setStarted(true)
          setSeed(null)
        }
      })
      .catch(() => {
        const draft = createConversation({ draft: true })
        setConversations([draft])
        setActiveId(draft.id)
        setStarted(true)
        setSeed(null)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 저장: 로그인=서버(디바운스), 게스트=로컬 (둘을 분리해 서로 안 섞임)
  useEffect(() => {
    const storable = conversations.filter(hasConversationContent)
    if (username && getToken()) {
      clearTimeout(syncTimer.current)
      syncTimer.current = setTimeout(() => {
        if (storable.length) bulkSaveConversations(storable).catch(() => {})
      }, 700)
      return () => clearTimeout(syncTimer.current)
    }
    saveConversations(storable)
    return undefined
  }, [conversations, username])

  function persist(list) {
    setConversations(list)
  }

  function newConversation(seedText = '') {
    const conv = createConversation()
    persist([conv, ...conversations])
    setActiveId(conv.id)
    setStarted(true)
    setSeed({ text: seedText, nonce: Date.now() })
  }

  function startAnalysis() {
    const recent = latestConversation(conversations)
    if (recent) {
      selectConversation(recent.id)
      return
    }
    newConversation('')
  }

  function goHome() {
    setStarted(false)
    setActiveId(null)
    setSeed(null)
  }

  function selectConversation(id) {
    setActiveId(id)
    setStarted(true)
    setSeed(null)
  }

  function handleMessagesChange(id, messages) {
    setConversations((prev) =>
      prev.map((c) =>
        c.id === id
          ? {
              ...c,
              messages,
              title: deriveTitle(messages, c.title),
              updatedAt: Date.now(),
              draft: messages.length > 0 ? false : c.draft,
            }
          : c
      )
    )
  }

  function handleInsight(id, insight) {
    const insightKey = insight?.price?.ticker || insight?.price?.name
    setConversations((prev) =>
      prev.map((c) =>
        c.id === id
          ? {
              ...c,
              updatedAt: Date.now(),
              draft: false,
              insights: (() => {
                const current = c.insights || []
                if (!insightKey) return [...current, insight]
                const existingIndex = current.findIndex((item) => {
                  const key = item?.price?.ticker || item?.price?.name
                  return key === insightKey
                })
                if (existingIndex < 0) return [...current, insight]
                return current.map((item, index) => (index === existingIndex ? insight : item))
              })(),
            }
          : c
      )
    )
  }

  function deleteConversation(id) {
    markConversationDeleted(id)
    const next = conversations.filter((c) => c.id !== id)
    const nextVisible = next.filter(hasConversationContent)
    setConversations(next)
    if (username && getToken()) deleteConversationRemote(id).catch(() => {})
    if (activeId === id) {
      if (nextVisible.length > 0) {
        const sorted = [...nextVisible].sort((a, b) => (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0))
        setActiveId(sorted[0].id)
        setStarted(true)
      } else {
        setActiveId(null)
        setStarted(false)
      }
    }
  }

  function toggleFavorite(id) {
    setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, favorite: !c.favorite } : c)))
  }

  // 로그인: 게스트 대화는 계정으로 이전하지 않고 버린 뒤 서버 목록만 로드
  async function handleAuthed(name) {
    setShowAuth(false)
    clearTimeout(syncTimer.current)
    saveConversations([])
    setConversations([])
    setActiveId(null)
    setSeed(null)
    setStarted(true)
    if (typeof window !== 'undefined') {
      window.location.reload()
      return
    }
    setUsername(name)
    let list = []
    try {
      retryDeletedConversationDeletes()
      const server = await fetchConversations()
      list = cleanServerConversations(server)
      setConversations(list)
    } catch {
      saveConversations([])
      setConversations([])
      // 서버 실패 시에도 게스트 대화는 계정 세션으로 넘기지 않는다.
    }
    // 로그인 후: 가장 최근 세션으로 바로 이동한다. 세션이 없으면 빈 세션을 열어
    // "분석 시작하기" 홈 화면이 로그인 직후 다시 뜨지 않게 한다.
    const pick = latestConversation(list)
    if (pick) {
      setActiveId(pick.id)
      setStarted(true)
      setSeed(null)
    } else {
      const conv = createConversation({ draft: true })
      setConversations([conv])
      setActiveId(conv.id)
      setStarted(true)
      setSeed(null)
    }
  }

  // 로그아웃: 화면 비움(게스트 대화는 이미 계정으로 이전됨)
  function handleLogout() {
    setAuth(null)
    setUsername(null)
    setConversations([])
    saveConversations([])
    setActiveId(null)
    setStarted(false)
  }

  const active = conversations.find((c) => c.id === activeId) || null
  const visibleConversations = conversations.filter(hasConversationContent)
  const insights = active?.insights || []
  const hasInsight = insights.length > 0

  return (
    <div className="relative min-h-screen bg-black text-neutral-100">
      <div className="fixed inset-0 z-0">
        <Aurora colorStops={AURORA_COLORS} blend={0.5} amplitude={1.0} speed={0.5} />
      </div>

      <NavBar
        username={username}
        onHome={goHome}
        onLoginClick={() => setShowAuth(true)}
        onLogout={handleLogout}
      />

      <Sidebar
        visible={started}
        conversations={visibleConversations}
        activeId={activeId}
        onSelect={selectConversation}
        onNew={() => newConversation('')}
        onDelete={deleteConversation}
        onToggleFavorite={toggleFavorite}
      />

      <main
        className={
          started && active
            ? 'relative z-10 flex h-screen flex-col overflow-hidden px-4 pb-4 pt-24 lg:pl-72 lg:pr-8'
            : 'relative z-10 mx-auto flex min-h-screen max-w-2xl flex-col px-4 pb-8 pt-28'
        }
      >
        {!started || !active ? (
          <div className="flex flex-1 flex-col items-center justify-center text-center animate-fade-in">
            <span className="mb-4 block font-mono text-xs uppercase tracking-[0.35em] text-neutral-400 drop-shadow">
              Stock Research Assistant
            </span>
            <h1 className="mb-5 text-4xl font-semibold leading-tight tracking-tight text-white drop-shadow-lg sm:text-5xl">
              <span className="block">차트는 결과를 보여줍니다.</span>
              <span className="block">우리는 이유를 찾아냅니다.</span>
            </h1>
            <p className="mb-10 max-w-lg text-balance text-neutral-300 drop-shadow">
              <span className="block">종목을 검색하면 뉴스와 공시를 분석해</span>
              <span className="block">주가 변동의 원인을 근거와 함께 설명합니다.</span>
              <span className="mt-3 block text-sm text-emerald-100/80">
                현재는 국내 상장 종목(KOSPI/KOSDAQ)만 지원하며, 미국 주식은 아직 제공하지 않습니다.
              </span>
            </p>
            <button
              type="button"
              onClick={startAnalysis}
              className="rounded-full border border-white/15 bg-white/10 px-8 py-4 text-base font-semibold text-white shadow-lg shadow-black/20 backdrop-blur-lg transition-all hover:scale-[1.03] hover:bg-white/20 active:scale-95"
            >
              분석 시작하기 →
            </button>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 items-stretch gap-6 animate-fade-in-up">
            <AnimatePresence>
              {hasInsight && (
                <motion.div
                  key="insight"
                  initial={{ width: 0, opacity: 0 }}
                  animate={{ width: '62%', opacity: 1 }}
                  exit={{ width: 0, opacity: 0 }}
                  transition={{ duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
                  className="hidden min-h-0 overflow-hidden lg:block"
                >
                  <div className="no-scrollbar flex h-full w-full flex-col gap-8 overflow-y-auto px-2 pb-2 pt-1">
                    {insights.map((ins, i) => (
                      <StockPanel
                        key={i}
                        price={ins.price}
                        news={ins.news}
                        disclosures={ins.disclosures}
                        disclosureError={ins.disclosureError}
                      />
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <motion.div
              layout
              className={`flex min-h-0 w-full max-w-2xl flex-1 flex-col ${hasInsight ? 'mx-auto lg:mx-0' : 'mx-auto'}`}
            >
              <ChatPanel
                key={active.id}
                sessionId={active.sessionId}
                initialMessages={active.messages}
                seed={seed}
                hint={ANALYSIS_HINT}
                onMessagesChange={(msgs) => handleMessagesChange(active.id, msgs)}
                onInsight={(insight) => handleInsight(active.id, insight)}
              />
            </motion.div>
          </div>
        )}

        <p className="mt-3 shrink-0 text-center font-mono text-xs text-neutral-500 drop-shadow">
          ※ 투자 자문이 아닌 참고용 정보입니다.
        </p>
      </main>

      {showAuth && <AuthModal onClose={() => setShowAuth(false)} onAuthed={handleAuthed} />}
    </div>
  )
}

export default App
