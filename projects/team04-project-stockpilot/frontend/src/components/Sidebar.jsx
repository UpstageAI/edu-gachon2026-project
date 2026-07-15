import { motion } from 'motion/react'

import LineSidebar from './LineSidebar'

function Sidebar({ conversations, activeId, onSelect, onNew, onDelete, onToggleFavorite, visible }) {
  // 즐겨찾기를 위쪽에 고정(안정 정렬 — 그룹 내 기존 순서 유지)
  const sorted = [...conversations].sort(
    (a, b) => (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0)
  )
  const items = sorted.map((c) => c.title || '새 대화')
  const stars = sorted.map((c) => !!c.favorite)
  const favCount = sorted.filter((c) => c.favorite).length
  const separatorAfter = favCount > 0 && favCount < sorted.length ? favCount : null
  const activeIndex = sorted.findIndex((c) => c.id === activeId)

  // 순서/즐겨찾기/개수가 바뀌면 LineSidebar를 다시 마운트해 활성 표시를 재동기화한다.
  const listKey = sorted.map((c) => (c.favorite ? '*' : '') + c.id).join('|')

  return (
    <motion.aside
      initial={false}
      onContextMenu={(e) => e.preventDefault()}
      animate={{ x: visible ? 0 : '-120%', opacity: visible ? 1 : 0 }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className="fixed bottom-4 left-4 top-24 z-20 hidden w-64 flex-col rounded-2xl border border-white/15 bg-white/10 p-4 shadow-lg shadow-black/20 backdrop-blur-lg lg:flex"
      style={{ pointerEvents: visible ? 'auto' : 'none' }}
    >
      <div className="mb-4 flex items-center justify-between">
        <span className="text-sm font-semibold text-neutral-200">내 대화</span>
        <button
          onClick={onNew}
          className="rounded-lg bg-emerald-500 px-2 py-1 text-xs font-semibold text-neutral-950 transition-colors hover:bg-emerald-400"
        >
          + 새 대화
        </button>
      </div>

      {/* 세로/가로 스크롤바 모두 숨김. 휠 스크롤은 그대로 동작한다. */}
      <div className="no-scrollbar flex-1 overflow-y-auto overflow-x-hidden">
        {conversations.length === 0 ? (
          <p className="px-1 py-4 text-xs text-neutral-400">아직 대화가 없어요.</p>
        ) : (
          <LineSidebar
            key={listKey}
            items={items}
            stars={stars}
            separatorAfter={separatorAfter}
            accentColor="#34d399"
            textColor="#c4c4c4"
            markerColor="#6c6c6c"
            markerLength={28}
            fontSize={0.95}
            itemGap={16}
            maxShift={26}
            defaultActive={activeIndex >= 0 ? activeIndex : null}
            onItemClick={(index) => onSelect(sorted[index].id)}
            onItemDelete={(index) => onDelete(sorted[index].id)}
            onItemFavorite={(index) => onToggleFavorite(sorted[index].id)}
          />
        )}
      </div>

      <p className="mt-3 px-1 text-center text-[11px] text-neutral-500">
        대화 위에서 우클릭 → 즐겨찾기 / 삭제
      </p>
    </motion.aside>
  )
}

export default Sidebar
