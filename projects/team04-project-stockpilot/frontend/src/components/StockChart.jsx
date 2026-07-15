import { useId } from 'react'
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

const CHART_HEIGHT = 260

function formatDateShort(d) {
  if (!d) return ''
  const [, m, day] = d.split('-')
  return `${m}/${day}`
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null
  const row = payload[0].payload
  const pct = row.change_pct
  const pctColor = pct > 0 ? 'text-red-400' : pct < 0 ? 'text-blue-400' : 'text-neutral-300'
  return (
    <div className="rounded-lg border border-white/15 bg-neutral-900/95 px-3 py-2 text-xs shadow-lg backdrop-blur">
      <p className="mb-1 text-neutral-400">{label}</p>
      <p className="font-semibold text-white">{Number(row.close).toLocaleString()}원</p>
      {pct != null && (
        <p className={pctColor}>{pct > 0 ? '▲' : pct < 0 ? '▼' : '―'} {Math.abs(pct).toFixed(2)}%</p>
      )}
    </div>
  )
}

function StockChart({ name, ohlcv, changePct }) {
  const gradId = `grad${useId().replace(/:/g, '')}`
  const data = (ohlcv || []).map((row) => ({ ...row, label: formatDateShort(row.date) }))
  const positive = (changePct ?? 0) >= 0
  const strokeColor = positive ? '#f87171' : '#60a5fa'

  return (
    <div className="flex flex-col">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-sm font-semibold text-neutral-200">{name || '종목'} 일봉</span>
        <span className="text-xs text-neutral-500">{data.length ? `최근 ${data.length}거래일` : ''}</span>
      </div>
      {/* 고정 높이 컨테이너 안에서 100%로 그려 높이 폭주를 막는다 */}
      <div style={{ height: CHART_HEIGHT }}>
        {data.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-neutral-500">
            차트 데이터를 불러오는 중이에요...
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={strokeColor} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={strokeColor} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="label" tick={{ fill: '#9ca3af', fontSize: 11 }} axisLine={{ stroke: 'rgba(255,255,255,0.1)' }} tickLine={false} minTickGap={24} />
              <YAxis
                domain={[
                  (dataMin) => dataMin - Math.abs(dataMin) * 0.02,
                  (dataMax) => dataMax + Math.abs(dataMax) * 0.02,
                ]}
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={54}
                tickFormatter={(v) => Number(v).toLocaleString()}
              />
              <Tooltip content={<CustomTooltip />} />
              <Area type="monotone" dataKey="close" stroke={strokeColor} strokeWidth={2} fill={`url(#${gradId})`} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

export default StockChart
