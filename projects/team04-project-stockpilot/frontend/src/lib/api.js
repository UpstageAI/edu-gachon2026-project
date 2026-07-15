// 백엔드 API 클라이언트 + 로컬 저장
const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000/api/v1";
const TOKEN_KEY = "stockpilot_token";
const USER_KEY = "stockpilot_user";
const CONV_KEY = "stockpilot_conversations";
const DELETED_CONV_KEY = "stockpilot_deleted_conversations";

export function getToken() { return localStorage.getItem(TOKEN_KEY); }
export function getUsername() { return localStorage.getItem(USER_KEY); }
export function setAuth(token, username) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, username || "");
  } else {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }
}

// ── 대화 목록 로컬 저장 ────────────────
export function loadConversations() {
  try { return JSON.parse(localStorage.getItem(CONV_KEY) || "[]"); }
  catch { return []; }
}
export function saveConversations(list) {
  localStorage.setItem(CONV_KEY, JSON.stringify(list));
}
export function loadDeletedConversationIds() {
  try { return new Set(JSON.parse(localStorage.getItem(DELETED_CONV_KEY) || "[]")); }
  catch { return new Set(); }
}
export function markConversationDeleted(id) {
  if (!id) return;
  const deleted = loadDeletedConversationIds();
  deleted.add(id);
  localStorage.setItem(DELETED_CONV_KEY, JSON.stringify([...deleted]));
}

async function jsonFetch(path, { method = "GET", body, auth = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const t = getToken();
    if (t) headers["Authorization"] = `Bearer ${t}`;
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method, headers, body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `요청 실패 (${res.status})`);
  return data;
}

export async function registerUser(username, password) {
  const data = await jsonFetch("/auth/register", { method: "POST", body: { username, password } });
  setAuth(data.access_token, data.username);
  return data;
}
export async function loginUser(username, password) {
  const data = await jsonFetch("/auth/login", { method: "POST", body: { username, password } });
  setAuth(data.access_token, data.username);
  return data;
}
export async function fetchWatchlist() { return jsonFetch("/watchlist/", { auth: true }); }
export async function addWatchlist(ticker, name) {
  return jsonFetch("/watchlist/", { method: "POST", body: { ticker, name }, auth: true });
}
export async function removeWatchlist(ticker) {
  return jsonFetch(`/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE", auth: true });
}

// ── 대화 서버 저장(로그인 사용자별) ────────────
export async function fetchConversations() {
  return jsonFetch("/conversations/", { auth: true });
}
export async function saveConversationRemote(conv) {
  return jsonFetch("/conversations/", { method: "PUT", body: conv, auth: true });
}
export async function bulkSaveConversations(list) {
  return jsonFetch("/conversations/bulk", { method: "POST", body: list, auth: true });
}
export async function deleteConversationRemote(id) {
  const data = await jsonFetch(`/conversations/${encodeURIComponent(id)}`, { method: "DELETE", auth: true });
  if (data?.ok === false) throw new Error("conversation delete failed");
  return data;
}

export async function streamChat(message, { sessionId = "web", model, onEvent, signal } = {}) {
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId, model }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`서버 오류 (${res.status})`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith("data:")) continue;
      try { onEvent(JSON.parse(line.slice(5).trim())); } catch { /* 무시 */ }
    }
  }
}
