import { useEffect, useRef, useState } from 'react'

import ResultCard from './ResultCard'
import { streamChat } from '../lib/api'

const MODEL_LABELS = {
  solar: 'Solar',
  'gpt-4o-mini': 'GPT-4o mini',
  'gemini-3.1-flash-lite': 'Gemini',
  'claude-haiku': 'Claude',
}

function modelFamily(value) {
  const v = String(value || '').toLowerCase()
  if (!v) return ''
  if (v === 'template-fallback') return 'template-fallback'
  if (v.startsWith('template-')) return 'template-intentional'
  if (v.includes('solar')) return 'solar'
  if (v.includes('gpt')) return 'gpt'
  if (v.includes('gemini')) return 'gemini'
  if (v.includes('claude')) return 'claude'
  if (v.includes('template')) return 'template'
  return v
}

function modelLabel(value) {
  const direct = MODEL_LABELS[value]
  if (direct) return direct
  const family = modelFamily(value)
  if (family === 'solar') return 'Solar'
  if (family === 'gpt') return 'GPT'
  if (family === 'gemini') return 'Gemini'
  if (family === 'claude') return 'Claude'
  if (value === 'template-market-overview') return '요즘 흐름 요약'
  if (value === 'template-direction-correction') return '방향 보정 요약'
  if (value === 'template-fallback') return '기본 템플릿'
  if (family === 'template-intentional') return '안전 요약 템플릿'
  if (family === 'template') return '기본 템플릿'
  return value || ''
}

function fallbackNotice(requestedModel, usedModel) {
  if (!requestedModel || !usedModel) return ''
  const requestedFamily = modelFamily(requestedModel)
  const usedFamily = modelFamily(usedModel)
  if (!requestedFamily || !usedFamily || requestedFamily === usedFamily) return ''
  if (usedFamily === 'template-intentional') return ''
  if (usedFamily === 'template' || usedFamily === 'template-fallback') {
    return `${modelLabel(requestedModel)} 응답에 실패해서 기본 템플릿으로 대체했습니다.`
  }
  return `${modelLabel(requestedModel)} 응답에 실패해서 ${modelLabel(usedModel)}로 대체했습니다.`
}

function ChatPanel({ sessionId, initialMessages, seed, hint, onMessagesChange, onInsight }) {
  const [messages, setMessages] = useState(initialMessages || [])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const [model, setModel] = useState(() => {
    try { return localStorage.getItem('sp_model') || 'solar' } catch { return 'solar' }
  })
  const listRef = useRef(null)
  const shouldScrollRef = useRef(false)

  // 새 메시지를 "입력"했을 때만 맨 아래로 스크롤한다(입력 순간 한 번).
  // 이후 응답 스트리밍 중에는 스크롤을 건드리지 않아 화면이 흔들리지 않는다.
  useEffect(() => {
    const el = listRef.current
    if (!el || !shouldScrollRef.current) return
    el.scrollTop = el.scrollHeight
    shouldScrollRef.current = false
  }, [messages])

  useEffect(() => {
    onMessagesChange(messages)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages])

  function patchLastAssistant(patch) {
    setMessages((prev) => {
      const next = [...prev]
      for (let i = next.length - 1; i >= 0; i--) {
        if (next[i].role === 'assistant') {
          const delta = typeof patch === 'function' ? patch(next[i]) : patch
          next[i] = { ...next[i], ...delta }
          break
        }
      }
      return next
    })
  }

  async function send(query) {
    if (!query || !query.trim() || busyRef.current) return
    const requestedModel = model
    busyRef.current = true
    setBusy(true)
    setInput('')
    shouldScrollRef.current = true   // 입력 순간에만 맨 아래로 내림
    setMessages((prev) => [
      ...prev,
      { role: 'user', text: query },
      {
        role: 'assistant',
        status: 'loading',
        thinking: '분석을 시작할게요...',
        price: null,
        answer: '',
        sources: [],
        terms: [],
        requestedModel,
        usedModel: '',
        modelNotice: '',
        errorMsg: '',
      },
    ])
    try {
      await streamChat(query, {
        sessionId,
        model: requestedModel,
        onEvent: (e) => {
          if (e.type === 'thinking') {
            patchLastAssistant({ thinking: e.content || '', status: 'loading' })
          } else if (e.type === 'tool') {
            const tr = e.tool_result || {}
            const news = Array.isArray(tr.news) ? tr.news.filter((n) => n && n.url) : []
            const disclosures = Array.isArray(tr.disclosures) ? tr.disclosures : []
            const shouldUpdatePanel = tr.panel_update !== false
            patchLastAssistant({
              price: tr.price || null,
              sources: news,
              status: 'streaming',
            })
            if (shouldUpdatePanel && Array.isArray(tr.stocks) && tr.stocks.length) {
              // 급등 스크리너: 종목별 차트·뉴스·공시를 순서대로 가운데에 쌓는다.
              tr.stocks.forEach((s) => {
                if (!s || !s.price) return
                const sNews = Array.isArray(s.news) ? s.news.filter((n) => n && n.url) : []
                onInsight?.({
                  price: s.price,
                  news: sNews,
                  disclosures: s.disclosures || [],
                  disclosureError: s.disclosure_error || '',
                })
              })
            } else if (shouldUpdatePanel && tr.price) {
              onInsight?.({
                price: tr.price,
                news,
                disclosures,
                disclosureError: tr.disclosure_error || '',
              })
            }
          } else if (e.type === 'token') {
            patchLastAssistant((m) => ({ status: 'streaming', answer: (m.answer || '') + (e.content || '') }))
          } else if (e.type === 'response') {
            const patch = {}
            if (e.content) patch.answer = e.content
            if (e.model) {
              patch.usedModel = e.model
              patch.modelNotice = fallbackNotice(requestedModel, e.model)
            }
            if (Object.keys(patch).length) patchLastAssistant(patch)
          } else if (e.type === 'glossary') {
            patchLastAssistant({ terms: e.terms || [] })
          } else if (e.type === 'error') {
            patchLastAssistant({ status: 'error', errorMsg: e.error || '오류가 발생했어요.' })
          } else if (e.type === 'done') {
            patchLastAssistant((m) => ({ status: m.status === 'error' ? 'error' : 'done' }))
          }
        },
      })
    } catch (err) {
      patchLastAssistant({
        status: 'error',
        errorMsg: err?.message || '서버에 연결하지 못했어요. 백엔드 상태를 확인해주세요.',
      })
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  useEffect(() => {
    if (seed && seed.text) send(seed.text)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed?.nonce])

  function handleSubmit(e) {
    e.preventDefault()
    send(input)
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      {/* 메시지 영역: 이 컨테이너 안에서만 스크롤 */}
      <div ref={listRef} className="no-scrollbar min-h-0 flex-1 space-y-4 overflow-y-auto pb-4">
        {messages.length === 0 && (
          <p className="mt-4 text-center text-neutral-400">
            {hint || '종목명을 입력하면 등락의 원인을 분석해드려요. (예: 삼성전자)'}
          </p>
        )}
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-emerald-500/90 px-4 py-2 text-neutral-950">
                {m.text}
              </div>
            </div>
          ) : (
            <ResultCard key={i} {...m} />
          )
        )}
      </div>

      {/* 입력창: 컬럼 하단에 고정 */}
      <form onSubmit={handleSubmit} className="shrink-0 pt-2">
        <div className="flex items-center gap-2 rounded-2xl border border-white/15 bg-white/10 p-2 backdrop-blur-lg">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy}
            placeholder="종목이나 궁금한 점을 입력하세요"
            className="flex-1 bg-transparent px-4 py-2 text-white placeholder-neutral-400 outline-none disabled:opacity-50"
          />
          <select
            value={model}
            onChange={(e) => {
              setModel(e.target.value)
              try { localStorage.setItem('sp_model', e.target.value) } catch { /* 무시 */ }
            }}
            disabled={busy}
            title="응답 생성에 사용할 모델 (실패 시 다른 모델로 자동 폴백)"
            className="rounded-xl border border-white/15 bg-white/5 px-2 py-2 text-sm text-neutral-200 outline-none disabled:opacity-50 [&>option]:text-black"
          >
            <option value="solar">Solar</option>
            <option value="gpt-4o-mini">GPT-4o mini</option>
            <option value="gemini-3.1-flash-lite">Gemini</option>
            <option value="claude-haiku">Claude</option>
          </select>
          <button
            type="submit"
            disabled={busy}
            className="rounded-xl bg-emerald-500 px-5 py-2 font-semibold text-neutral-950 transition-colors hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? '분석 중' : '전송'}
          </button>
        </div>
      </form>
    </div>
  )
}

export default ChatPanel
