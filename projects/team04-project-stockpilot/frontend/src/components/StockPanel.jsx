import BorderGlow from './BorderGlow'
import DisclosureList from './DisclosureList'
import NewsList from './NewsList'
import StockChart from './StockChart'

// 테두리 글로우 공통 설정 (테마: 에메랄드/스카이/바이올렛). glowRadius를 작게 잡아 옆 카드로 번지지 않게.
const GLOW = {
  glowColor: '155 80 60',
  backgroundColor: '#0c1210',
  glowRadius: 16,
  coneSpread: 25,
  edgeSensitivity: 28,
  colors: ['#34d399', '#38bdf8', '#a78bfa'],
}

function formatPct(p) {
  if (p == null) return null
  const a = Math.abs(p).toFixed(2)
  if (p > 0) return { text: `▲ ${a}%`, cls: 'text-red-400' }
  if (p < 0) return { text: `▼ ${a}%`, cls: 'text-blue-400' }
  return { text: `― ${a}%`, cls: 'text-neutral-300' }
}

function StockPanel({ price, news, disclosures, disclosureError }) {
  if (!price) return null
  const pct = formatPct(price.change_pct)

  return (
    <div className="flex w-full flex-col gap-4">
      {/* 종목별 헤더 */}
      <div className="flex items-baseline gap-3 px-1">
        <span className="text-base font-semibold text-white">{price.name || '종목'}</span>
        {price.current_price != null && (
          <span className="text-sm text-neutral-300">{Number(price.current_price).toLocaleString()}원</span>
        )}
        {pct && <span className={`text-sm font-medium ${pct.cls}`}>{pct.text}</span>}
      </div>

      {/* 위: 차트(크게) + 뉴스 — 각 카드는 콘텐츠 크기로 확정(삐져나옴/겹침 방지) */}
      <div className="grid grid-cols-1 items-start gap-4 sm:grid-cols-5">
        <BorderGlow {...GLOW} borderRadius={16} className="sm:col-span-3">
          <div className="p-5">
            <StockChart name={price.name} ohlcv={price.ohlcv} changePct={price.change_pct} />
          </div>
        </BorderGlow>
        <BorderGlow {...GLOW} borderRadius={16} className="sm:col-span-2">
          <div className="p-5">
            <div className="h-[292px]">
              <NewsList news={news} />
            </div>
          </div>
        </BorderGlow>
      </div>

      {/* 아래: 공시정보 */}
      <BorderGlow {...GLOW} borderRadius={24}>
        <div className="px-6 py-4">
          <DisclosureList disclosures={disclosures} error={disclosureError} />
        </div>
      </BorderGlow>
    </div>
  )
}

export default StockPanel
