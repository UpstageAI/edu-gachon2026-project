/**
 * 로컬 저장 + 표시 유틸.
 *
 * History/Saved 는 백엔드 저장소가 없어(로그인 없음, 세션 히스토리는 30분 TTL 캐시)
 * 이 브라우저의 localStorage 에 보관한다 — 새로고침·재방문에도 남고, 서버 불필요.
 * ponytail: 단일 브라우저 로컬 저장. 여러 기기 동기화가 필요해지면 백엔드 저장 API 로 승격.
 */
const HKEY = "querypal.history";
const SKEY = "querypal.saved";
const MAX_HISTORY = 50;

function read(key) {
  try {
    const v = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}
function write(key, v) {
  try {
    localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* 용량 초과 등은 무시 (히스토리는 필수 아님) */
  }
}

export function getHistory() {
  return read(HKEY);
}

/** 성공 턴 1건 기록: {q, sql, tables, rowCount, ts}. 같은 질문 최신화(중복 제거). */
export function addHistory(entry) {
  const now = { ...entry, ts: Date.now() };
  const rest = read(HKEY).filter((h) => h.q !== entry.q);
  write(HKEY, [now, ...rest].slice(0, MAX_HISTORY));
}

export function getSaved() {
  return read(SKEY);
}
export function isSaved(id) {
  return read(SKEY).some((s) => s.id === id);
}
/** 저장 토글. entry.id 로 식별. 반환: 저장됨 여부(true=방금 저장). */
export function toggleSaved(entry) {
  const cur = read(SKEY);
  if (cur.some((s) => s.id === entry.id)) {
    write(SKEY, cur.filter((s) => s.id !== entry.id));
    return false;
  }
  write(SKEY, [{ ...entry, ts: Date.now() }, ...cur]);
  return true;
}

// ── 표시 포맷 ──
export function fmtInt(n) {
  const v = Number(n) || 0;
  return v.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
}
export function fmtCost(usd) {
  const v = Number(usd) || 0;
  if (v === 0) return "$0";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}
export function fmtLatency(ms) {
  const v = Number(ms) || 0;
  return v >= 1000 ? `${(v / 1000).toFixed(1)}초` : `${Math.round(v)}ms`;
}
/** 상대 시간 ("방금 전", "2시간 전", "어제", "M월 D일") */
export function relTime(ts) {
  const diff = Date.now() - ts;
  const m = Math.floor(diff / 60000);
  if (m < 1) return "방금 전";
  if (m < 60) return `${m}분 전`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}시간 전`;
  const d = Math.floor(h / 24);
  if (d === 1) return "어제";
  if (d < 7) return `${d}일 전`;
  const dt = new Date(ts);
  return `${dt.getMonth() + 1}월 ${dt.getDate()}일`;
}

/** 컬럼이 숫자열인지(모든 값이 number) — 우측정렬·차트 대상 판별 */
export function isNumericCol(rows, idx) {
  return rows.length > 0 && rows.every((r) => typeof r[idx] === "number");
}

/** columns/rows → CSV 다운로드 */
export function downloadCsv(columns, rows, filename = "result.csv") {
  const esc = (v) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [columns.map(esc).join(",")];
  for (const r of rows) lines.push(r.map(esc).join(","));
  const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
