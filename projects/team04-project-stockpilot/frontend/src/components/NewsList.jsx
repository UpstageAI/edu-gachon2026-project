function NewsList({ news }) {
  const items = news || []

  return (
    <div className="flex h-full min-h-[220px] flex-col">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-sm font-semibold text-neutral-200">관련 뉴스</span>
        <span className="text-xs text-neutral-500">{items.length}건</span>
      </div>
      {items.length === 0 ? (
        <div className="flex flex-1 items-center justify-center text-sm text-neutral-500">
          관련 뉴스를 찾지 못했어요.
        </div>
      ) : (
        <ul className="no-scrollbar flex-1 space-y-2 overflow-y-auto overflow-x-hidden pr-1">
          {items.map((item, i) => (
            <li key={i}>
              <a
                href={item.url}
                target="_blank"
                rel="noreferrer"
                className="block rounded-xl border border-white/10 bg-white/5 px-3 py-2 transition-colors hover:border-emerald-400/40 hover:bg-white/10"
              >
                <p className="line-clamp-2 text-sm text-neutral-100">{item.title}</p>
                <p className="mt-1 text-xs text-neutral-500">
                  {item.source || '기사'}
                  {item.session ? ` · ${item.session}` : ''}
                </p>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default NewsList
