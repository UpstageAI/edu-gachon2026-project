import { isNumericCol } from "../store.js";

/** 백엔드 결과 {columns:[], rows:[[...]]} 를 표로. 숫자열은 우측정렬+모노. */
export default function ResultTable({ columns, rows }) {
  if (!columns || columns.length === 0) return null;
  const numeric = columns.map((_, i) => isNumericCol(rows, i));

  return (
    <div className="table-wrap card" style={{ boxShadow: "0 1px 3px rgba(16,24,40,.05)" }}>
      <table className="result">
        <thead>
          <tr>
            {columns.map((c, i) => (
              <th key={i} className={numeric[i] ? "num" : ""}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={ri}>
              {r.map((cell, ci) => (
                <td key={ci} className={numeric[ci] ? "num" : ""}>
                  {typeof cell === "number" ? cell.toLocaleString("ko-KR") : String(cell ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
