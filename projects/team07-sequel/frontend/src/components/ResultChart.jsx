import { isNumericCol } from "../store.js";

/** 결과를 세로 막대 차트로. 라벨 = 첫 텍스트 컬럼, 값 = 마지막 숫자 컬럼.
 *  숫자 컬럼이 없으면 null(호출부에서 표 폴백). 최대 12개 막대만 표시. */
export default function ResultChart({ columns, rows }) {
  if (!columns || rows.length === 0) return null;

  let valIdx = -1;
  for (let i = columns.length - 1; i >= 0; i--) {
    if (isNumericCol(rows, i)) {
      valIdx = i;
      break;
    }
  }
  if (valIdx === -1) return null;
  const labelIdx = columns.findIndex((_, i) => !isNumericCol(rows, i));
  const li = labelIdx === -1 ? 0 : labelIdx;

  const data = rows.slice(0, 12).map((r) => ({ label: String(r[li] ?? ""), value: Number(r[valIdx]) || 0 }));
  const max = Math.max(...data.map((d) => d.value), 1);

  return (
    <div className="card chart-card">
      <div className="chart-title">{columns[valIdx]} (상위 {data.length}개)</div>
      <div className="chart">
        {data.map((d, i) => (
          <div key={i} className="bar-col">
            <div className="bar-val">{d.value.toLocaleString("ko-KR")}</div>
            <div className="bar" style={{ height: `${Math.max((d.value / max) * 100, 2)}%` }} />
            <div className="bar-lbl" title={d.label}>
              {d.label.length > 8 ? d.label.slice(0, 8) + "…" : d.label}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
