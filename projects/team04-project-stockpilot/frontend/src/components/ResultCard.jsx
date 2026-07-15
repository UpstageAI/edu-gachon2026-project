import GlossaryAnswer from './GlossaryAnswer'

function responseMetaLabel(m) {
  if (!m) return ''
  let s = String(m)
  if (s.includes('/')) s = s.split('/').pop()   // gemini/gemini-2.0-flash → gemini-2.0-flash
  if (s.toLowerCase().includes('template')) return ''
  return s
}

function responseMetaText(m) {
  const label = responseMetaLabel(m)
  if (!label) return ''
  return `사용 모델: ${label}`
}

function formatPct(p) {
  const a = Math.abs(p).toFixed(2)
  if (p > 0) return `▲ ${a}%`
  if (p < 0) return `▼ ${a}%`
  return `― ${a}%`
}
function colorFor(p) {
  if (p > 0) return 'text-red-400'
  if (p < 0) return 'text-blue-400'
  return 'text-neutral-300'
}
function dirWord(p) {
  if (p > 0) return '상승'
  if (p < 0) return '하락'
  return '보합'
}

function formatDate(value) {
  if (!value) return '확인 불가'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date)
}

function formatDateTime(value) {
  if (!value) return '확인 불가'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function ResultCard({ status, thinking, price, answer, sources, errorMsg, terms, usedModel, modelNotice }) {
  const pct = price && price.change_pct !== null && price.change_pct !== undefined
    ? Number(price.change_pct)
    : null
  const hasPct = pct !== null && !Number.isNaN(pct)
  const showThinking = status === 'loading' && !answer
  const responseMeta = responseMetaText(usedModel)

  return (
    <div className="w-full rounded-2xl border border-white/15 bg-white/5 p-6 backdrop-blur-lg">
      {modelNotice && (
        <div className="mb-2 rounded-xl border border-amber-300/30 bg-amber-300/10 px-3 py-2 text-sm text-amber-100">
          ⚠️ {modelNotice}
        </div>
      )}
      {responseMeta && (
        <p className="mb-2 text-[12px] text-neutral-500">
          {responseMeta}
        </p>
      )}
      {showThinking && (
        <div className="flex items-center gap-2 text-neutral-300">
          <span className="flex gap-1">
            <span className="think-dot h-1.5 w-1.5 rounded-full bg-emerald-400" />
            <span className="think-dot h-1.5 w-1.5 rounded-full bg-emerald-400" />
            <span className="think-dot h-1.5 w-1.5 rounded-full bg-emerald-400" />
          </span>
          <span>{thinking || '생각 중입니다...'}</span>
        </div>
      )}

      {status === 'error' && <p className="text-red-300">{errorMsg}</p>}

      {hasPct && (
        <div className="mb-1 flex items-baseline gap-3">
          <span className="text-lg text-neutral-200">{price.name || '종목'}</span>
          <span className={`text-4xl font-bold ${colorFor(pct)}`}>
            {formatPct(pct)}
          </span>
          <span className="text-sm text-neutral-400">{dirWord(pct)}</span>
        </div>
      )}
      {price && price.current_price != null && (
        <p className="text-neutral-300">
          현재가 {Number(price.current_price).toLocaleString()}원
        </p>
      )}
      {price && (
        <p className="mb-4 mt-2 text-xs leading-relaxed text-neutral-500">
          일봉 기준 · 등락률은 전 거래일 대비 · 기준일 {formatDate(price.as_of)} · 조회시각{' '}
          {formatDateTime(price.snapshot_at)}
        </p>
      )}

      {answer && <GlossaryAnswer text={answer} terms={terms} />}

      {sources && sources.length > 0 && (
        <div className="mt-5">
          <p className="mb-2 text-sm text-neutral-400">출처</p>
          <div className="flex flex-wrap gap-2">
            {sources.map((s, i) => (
              <a
                key={i}
                href={s.url}
                target="_blank"
                rel="noreferrer"
                title={s.title || ''}
                className="rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-sm text-neutral-200 transition-colors hover:border-emerald-400/50 hover:text-white"
              >
                {s.source || '기사'} ↗
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default ResultCard
