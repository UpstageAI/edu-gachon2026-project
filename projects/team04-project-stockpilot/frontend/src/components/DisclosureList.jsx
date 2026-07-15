function formatDate(d) {
  if (!d) return ''
  if (/^\d{8}$/.test(d)) return `${d.slice(0, 4)}.${d.slice(4, 6)}.${d.slice(6, 8)}`
  return d
}

function DisclosureList({ disclosures, error }) {
  const items = disclosures || []

  return (
    <div className="w-full">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-sm font-semibold text-neutral-200">공시정보</span>
        <span className="text-xs text-neutral-500">{items.length}건 · DART</span>
      </div>
      {items.length === 0 ? (
        <p className="py-3 text-sm text-neutral-500">
          {error
            ? '공시 조회가 지연돼 이번 응답에는 생략됐어요. 잠시 뒤 다시 물어보면 캐시된 결과로 더 빨라질 수 있어요.'
            : '최근 공시를 찾지 못했어요.'}
        </p>
      ) : (
        <ul className="no-scrollbar flex max-h-40 flex-col gap-1.5 overflow-y-auto overflow-x-hidden pr-1">
          {items.map((d, i) => (
            <li key={i}>
              <a
                href={d.url}
                target="_blank"
                rel="noreferrer"
                className="flex items-baseline justify-between gap-3 rounded-xl px-3 py-2 transition-colors hover:bg-white/10"
              >
                <span className="line-clamp-1 text-sm text-neutral-100">{d.title}</span>
                <span className="shrink-0 font-mono text-xs text-neutral-500">{formatDate(d.date)}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default DisclosureList
