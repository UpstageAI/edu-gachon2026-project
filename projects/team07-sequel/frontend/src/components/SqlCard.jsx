import { useState } from "react";

// 디자인 스펙의 SQL 카드 색. 정식 파서 대신 가벼운 토크나이저로 충분(생성 SQL 표시용).
const KEYWORDS =
  /\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|ON|GROUP BY|ORDER BY|HAVING|LIMIT|OFFSET|AS|AND|OR|NOT|IN|IS|NULL|DESC|ASC|COUNT|SUM|AVG|MIN|MAX|DISTINCT|CASE|WHEN|THEN|ELSE|END|WITH|UNION|ALL|BETWEEN|LIKE|EXTRACT|DATE|INTERVAL)\b/gi;
const COL = { kw: "#7CA9FF", str: "#7EE6B0", num: "#F2B36B", com: "#5B6B85" };

/** SQL 문자열 → 색상 span 배열 (dangerouslySetInnerHTML 미사용, XSS 안전). */
function highlight(sql) {
  // 우선 comment / string 을 통째로 잘라내고, 나머지에서 keyword/number 강조
  const parts = [];
  const re = /(--[^\n]*)|('(?:[^']|'')*')/g;
  let last = 0;
  let m;
  let key = 0;
  const pushPlain = (text) => {
    // keyword / number 강조
    let li = 0;
    let km;
    const kre = new RegExp(`${KEYWORDS.source}|\\b\\d+(?:\\.\\d+)?\\b`, "gi");
    while ((km = kre.exec(text))) {
      if (km.index > li) parts.push(<span key={key++}>{text.slice(li, km.index)}</span>);
      const tok = km[0];
      const isNum = /^\d/.test(tok);
      parts.push(
        <span key={key++} style={{ color: isNum ? COL.num : COL.kw }}>
          {tok}
        </span>
      );
      li = km.index + tok.length;
    }
    if (li < text.length) parts.push(<span key={key++}>{text.slice(li)}</span>);
  };

  while ((m = re.exec(sql))) {
    if (m.index > last) pushPlain(sql.slice(last, m.index));
    const isComment = m[0].startsWith("--");
    parts.push(
      <span key={key++} style={{ color: isComment ? COL.com : COL.str }}>
        {m[0]}
      </span>
    );
    last = m.index + m[0].length;
  }
  if (last < sql.length) pushPlain(sql.slice(last));
  return parts;
}

export default function SqlCard({ sql }) {
  const [copied, setCopied] = useState(false);
  if (!sql) return null;

  function copy() {
    navigator.clipboard?.writeText(sql).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => {}
    );
  }

  return (
    <div className="sql-card">
      <div className="sql-head">
        <span className="tl" style={{ background: "#FF5F57" }} />
        <span className="tl" style={{ background: "#FEBC2E" }} />
        <span className="tl" style={{ background: "#28C840" }} />
        <span className="sql-name">generated_query.sql</span>
        <button className="sql-copy" onClick={copy}>
          {copied ? "✓ 복사됨" : "⧉ 복사"}
        </button>
      </div>
      <pre className="sql-pre">{highlight(sql)}</pre>
    </div>
  );
}
