import { useState, useRef, type KeyboardEvent } from "react";

interface Props {
  onSend: (text: string) => void;
  disabled?: boolean;
}

export default function ChatInput({ onSend, disabled }: Props) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  };

  return (
    <div
      style={{
        padding: "12px 20px 20px",
        background: "#f7f8fb",
        borderTop: "1px solid #e2e5ec",
      }}
    >
      <div
        style={{
          maxWidth: "780px",
          margin: "0 auto",
          position: "relative",
          display: "flex",
          alignItems: "flex-end",
          gap: "10px",
          background: "#ffffff",
          border: "1px solid #e2e5ec",
          borderRadius: "16px",
          padding: "10px 12px 10px 16px",
          boxShadow: "0 0 0 1px transparent",
          transition: "border-color 0.2s, box-shadow 0.2s",
        }}
        onFocusCapture={(e) => {
          const el = e.currentTarget as HTMLDivElement;
          el.style.borderColor = "#4f7ef8";
          el.style.boxShadow = "0 0 0 3px #4f7ef820";
        }}
        onBlurCapture={(e) => {
          const el = e.currentTarget as HTMLDivElement;
          el.style.borderColor = "#e2e5ec";
          el.style.boxShadow = "0 0 0 1px transparent";
        }}
      >
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          disabled={disabled}
          placeholder="청년 정책 및 훈련에 대해 질문해 주세요..."
          rows={1}
          style={{
            flex: 1,
            background: "transparent",
            border: "none",
            outline: "none",
            resize: "none",
            color: "#1f2430",
            fontSize: "14px",
            lineHeight: 1.6,
            fontFamily: "inherit",
            padding: "2px 0",
            maxHeight: "160px",
            overflowY: "auto",
          }}
        />

        <button
          onClick={handleSend}
          disabled={!value.trim() || disabled}
          style={{
            width: "36px",
            height: "36px",
            borderRadius: "10px",
            background: value.trim() && !disabled ? "#4f7ef8" : "#eef1f7",
            border: "none",
            cursor: value.trim() && !disabled ? "pointer" : "default",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
            transition: "background 0.15s",
            color: value.trim() && !disabled ? "#fff" : "#9aa0b4",
          }}
          onMouseEnter={(e) => {
            if (value.trim() && !disabled)
              (e.currentTarget as HTMLButtonElement).style.background = "#6b93fa";
          }}
          onMouseLeave={(e) => {
            if (value.trim() && !disabled)
              (e.currentTarget as HTMLButtonElement).style.background = "#4f7ef8";
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
          </svg>
        </button>
      </div>

      <div style={{ textAlign: "center", marginTop: "8px", fontSize: "11px", color: "#8a90a3" }}>
        주민등록번호·연락처·계좌번호는 입력하지 마세요. 감지된 민감정보는 전송하지 않고 삭제 처리합니다.
      </div>
    </div>
  );
}
