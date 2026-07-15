import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const TIP_W = 288 // 툴팁 너비(px)

function isAsciiTokenChar(ch) {
  return !!ch && /[A-Za-z0-9]/.test(ch)
}

function needsAsciiBoundary(surface) {
  return /[A-Za-z0-9]/.test(surface) && !/[가-힣]/.test(surface)
}

function isValidSurfaceMatch(str, index, surface) {
  if (!needsAsciiBoundary(surface)) return true
  const before = index > 0 ? str[index - 1] : ''
  const after = index + surface.length < str.length ? str[index + surface.length] : ''
  return !isAsciiTokenChar(before) && !isAsciiTokenChar(after)
}

// LLM 답변을 마크다운으로 렌더링하면서, RAG 용어 사전에 있는 단어에는
// 밑줄 + 클릭 시 나무위키식 각주(정의 툴팁)를 붙인다.
// 툴팁은 createPortal로 body 최상단에 fixed로 띄워 채팅/패널의 overflow에 잘리지 않게 한다.
function GlossaryAnswer({ text, terms }) {
  const [tip, setTip] = useState(null) // { key, term, left, top, bottom } | null

  useEffect(() => {
    if (!tip) return undefined
    const close = () => setTip(null)
    document.addEventListener('pointerdown', close)
    document.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [tip])

  if (!text) return null

  const list = (terms || []).filter((t) => t && t.matched_text)
  const sorted = [...list].sort((a, b) => b.matched_text.length - a.matched_text.length)

  let seq = 0

  function toggle(e, key, term) {
    e.stopPropagation()
    if (tip && tip.key === key) {
      setTip(null)
      return
    }
    const r = e.currentTarget.getBoundingClientRect()
    setTip({ key, term, left: r.left, top: r.top, bottom: r.bottom })
  }

  function renderString(str, keyBase) {
    if (!sorted.length) return str
    const nodes = []
    let cursor = 0

    while (cursor < str.length) {
      let best = null
      for (const term of sorted) {
        const surface = term.matched_text
        let index = str.indexOf(surface, cursor)
        while (index >= 0 && !isValidSurfaceMatch(str, index, surface)) {
          index = str.indexOf(surface, index + 1)
        }
        if (index < 0) continue
        if (
          !best
          || index < best.index
          || (index === best.index && surface.length > best.surface.length)
        ) {
          best = { term, surface, index }
        }
      }

      if (!best) {
        nodes.push(<span key={`${keyBase}-tail-${cursor}`}>{str.slice(cursor)}</span>)
        break
      }

      if (best.index > cursor) {
        nodes.push(<span key={`${keyBase}-t${cursor}`}>{str.slice(cursor, best.index)}</span>)
      }

      const key = `${best.term.term}-${seq++}`
      nodes.push(
        <button
          key={key}
          type="button"
          onClick={(e) => toggle(e, key, best.term)}
          className="cursor-pointer text-emerald-300 underline decoration-dotted decoration-emerald-400/50 underline-offset-4 transition-colors hover:text-emerald-200"
        >
          {best.surface}
        </button>
      )

      cursor = best.index + best.surface.length
    }

    return nodes
  }

  function decorate(children, keyBase) {
    const arr = Array.isArray(children) ? children : [children]
    return arr.map((child, i) =>
      typeof child === 'string' ? (
        <span key={`${keyBase}-s${i}`}>{renderString(child, `${keyBase}-${i}`)}</span>
      ) : (
        child
      )
    )
  }

  const components = {
    p: ({ children }) => <p className="mb-3 leading-relaxed last:mb-0">{decorate(children, 'p')}</p>,
    li: ({ children }) => <li className="leading-relaxed">{decorate(children, 'li')}</li>,
    ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>,
    ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>,
    strong: ({ children }) => <strong className="font-semibold text-white">{decorate(children, 'strong')}</strong>,
    em: ({ children }) => <em className="italic">{decorate(children, 'em')}</em>,
    del: ({ children }) => <del className="opacity-70">{decorate(children, 'del')}</del>,
    h1: ({ children }) => <h1 className="mb-2 mt-4 text-lg font-semibold text-white first:mt-0">{decorate(children, 'h1')}</h1>,
    h2: ({ children }) => <h2 className="mb-2 mt-4 text-base font-semibold text-white first:mt-0">{decorate(children, 'h2')}</h2>,
    h3: ({ children }) => <h3 className="mb-1 mt-3 text-sm font-semibold text-neutral-100 first:mt-0">{decorate(children, 'h3')}</h3>,
    a: ({ href, children }) => (
      <a href={href} target="_blank" rel="noreferrer" className="text-emerald-300 underline decoration-emerald-400/40 underline-offset-2 hover:text-emerald-200">
        {decorate(children, 'a')}
      </a>
    ),
    blockquote: ({ children }) => <blockquote className="mb-3 border-l-2 border-white/20 pl-3 text-neutral-300 last:mb-0">{children}</blockquote>,
    code: ({ children }) => <code className="rounded bg-white/10 px-1 py-0.5 font-mono text-[0.85em] text-emerald-200">{children}</code>,
    pre: ({ children }) => <pre className="mb-3 overflow-x-auto rounded-lg bg-black/40 p-3 font-mono text-xs text-neutral-200 last:mb-0">{children}</pre>,
    table: ({ children }) => (
      <div className="mb-3 overflow-x-auto last:mb-0">
        <table className="w-full border-collapse text-sm">{children}</table>
      </div>
    ),
    th: ({ children }) => <th className="border border-white/15 px-2 py-1 text-left font-semibold text-neutral-200">{decorate(children, 'th')}</th>,
    td: ({ children }) => <td className="border border-white/10 px-2 py-1 text-neutral-100">{decorate(children, 'td')}</td>,
  }

  let tipStyle = null
  if (tip) {
    const vw = typeof window !== 'undefined' ? window.innerWidth : 1280
    const vh = typeof window !== 'undefined' ? window.innerHeight : 800
    const left = Math.max(8, Math.min(tip.left, vw - TIP_W - 8))
    const openUp = vh - tip.bottom < 200
    tipStyle = openUp
      ? { position: 'fixed', left, bottom: vh - tip.top + 6, zIndex: 1000 }
      : { position: 'fixed', left, top: tip.bottom + 6, zIndex: 1000 }
  }

  return (
    <div className="relative text-neutral-100">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
      {tip &&
        createPortal(
          <div
            style={tipStyle}
            onPointerDown={(e) => e.stopPropagation()}
            className="w-72 max-w-[18rem] rounded-xl border border-white/15 bg-neutral-900/95 p-3 text-left text-sm normal-case leading-relaxed text-neutral-200 shadow-xl backdrop-blur"
          >
            <span className="mb-1 block text-xs font-semibold text-emerald-300">{tip.term.term}</span>
            <span className="block text-neutral-300">{tip.term.definition}</span>
            {tip.term.example && <span className="mt-2 block text-xs text-neutral-500">예) {tip.term.example}</span>}
          </div>,
          document.body,
        )}
    </div>
  )
}

export default GlossaryAnswer
