import type { Chat } from "../types";

interface Props {
  chats: Chat[];
  activeChatId: string | null;
  onSelectChat: (id: string) => void;
  onNewChat: () => void;
  onDeleteChat: (id: string) => void;
  onClearChats: () => void;
  isOpen: boolean;
  onClose: () => void;
}

function formatTime(date: Date): string {
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 전`;
  return `${Math.floor(hours / 24)}일 전`;
}

export default function Sidebar({ chats, activeChatId, onSelectChat, onNewChat, onDeleteChat, onClearChats, isOpen, onClose }: Props) {
  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          style={{ position: "fixed", inset: 0, background: "#00000088", zIndex: 40 }}
          onClick={onClose}
        />
      )}

      <aside
        style={{
          width: "260px",
          minWidth: "260px",
          height: "100%",
          background: "#ffffff",
          borderRight: "1px solid #e2e5ec",
          display: "flex",
          flexDirection: "column",
          position: "relative",
          zIndex: 50,
          transition: "transform 0.25s ease",
        }}
      >
        {/* Logo */}
        <div
          style={{
            padding: "20px 16px 16px",
            borderBottom: "1px solid #e2e5ec",
            display: "flex",
            alignItems: "center",
            gap: "10px",
          }}
        >
          <div
            style={{
              width: "32px",
              height: "32px",
              borderRadius: "8px",
              background: "linear-gradient(135deg, #4f7ef8, #38c96e)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "16px",
              flexShrink: 0,
            }}
          >
            🧭
          </div>
          <div>
            <div style={{ fontSize: "15px", fontWeight: 700, color: "#1f2430", lineHeight: 1 }}>
              정책나침반
            </div>
            <div style={{ fontSize: "11px", color: "#6b7280", marginTop: "2px" }}>
              청년정책·훈련 AI
            </div>
          </div>
        </div>

        {/* New chat button */}
        <div style={{ padding: "12px" }}>
          <button
            onClick={onNewChat}
            style={{
              width: "100%",
              padding: "10px 14px",
              background: "#eef1f7",
              border: "1px solid #e2e5ec",
              borderRadius: "10px",
              color: "#1f2430",
              fontSize: "13.5px",
              fontWeight: 600,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "8px",
              transition: "background 0.15s, border-color 0.15s",
            }}
            onMouseEnter={(e) => {
              const b = e.currentTarget as HTMLButtonElement;
              b.style.background = "#e2e8f5";
              b.style.borderColor = "#4f7ef8";
            }}
            onMouseLeave={(e) => {
              const b = e.currentTarget as HTMLButtonElement;
              b.style.background = "#eef1f7";
              b.style.borderColor = "#e2e5ec";
            }}
          >
            <span style={{ fontSize: "16px", lineHeight: 1 }}>+</span>
            새 채팅
          </button>
        </div>

        {/* Chat list */}
        <div style={{ flex: 1, overflowY: "auto", padding: "0 12px 12px" }}>
          <div style={{ fontSize: "11px", color: "#6b7280", fontWeight: 600, padding: "8px 4px 6px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            최근 대화
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
            {chats.map((chat) => (
              <div
                key={chat.id}
                style={{
                  width: "100%",
                  background: activeChatId === chat.id ? "#eef1f7" : "transparent",
                  border: "1px solid",
                  borderColor: activeChatId === chat.id ? "#e2e5ec" : "transparent",
                  borderRadius: "8px",
                  display: "flex",
                  alignItems: "center",
                  gap: "2px",
                }}
              >
                <button
                  onClick={() => onSelectChat(chat.id)}
                  style={{
                    flex: 1,
                    minWidth: 0,
                    padding: "9px 8px",
                    background: "transparent",
                    border: "none",
                    textAlign: "left",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ fontSize: "13px", color: "#1f2430", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", lineHeight: 1.4 }}>
                    {chat.title}
                  </div>
                  <div style={{ fontSize: "11px", color: "#6b7280", marginTop: "2px" }}>
                    {formatTime(chat.createdAt)}
                  </div>
                </button>
                <button
                  onClick={() => onDeleteChat(chat.id)}
                  aria-label={`${chat.title} 삭제`}
                  title="채팅 삭제"
                  style={{
                    width: "28px",
                    height: "28px",
                    marginRight: "4px",
                    background: "transparent",
                    border: "none",
                    borderRadius: "6px",
                    color: "#8a90a3",
                    cursor: "pointer",
                    fontSize: "16px",
                  }}
                >
                  ×
                </button>
              </div>
            ))}
            {chats.length === 0 && (
              <div style={{ padding: "18px 8px", fontSize: "12px", color: "#8a90a3", textAlign: "center" }}>
                저장된 대화가 없어요.
              </div>
            )}
          </div>
          {chats.length > 0 && (
            <button
              onClick={onClearChats}
              style={{
                width: "100%",
                marginTop: "12px",
                padding: "8px",
                background: "transparent",
                border: "none",
                color: "#8a90a3",
                fontSize: "11.5px",
                cursor: "pointer",
              }}
            >
              전체 기록 삭제
            </button>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: "12px 16px",
            borderTop: "1px solid #e2e5ec",
            fontSize: "11.5px",
            color: "#6b7280",
            display: "flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          <span>🏛️</span>
          <span>공공데이터 기반 AI 서비스</span>
        </div>
      </aside>
    </>
  );
}
