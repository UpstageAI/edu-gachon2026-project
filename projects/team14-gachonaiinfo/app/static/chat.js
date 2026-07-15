const chatForm = document.getElementById("chat-form");
const messageInput = document.getElementById("message-input");
const chatBox = document.getElementById("chat-box");
const sendButton = document.getElementById("send-button");
const quickQuestions = document.querySelectorAll(".quick-question");

let loadingMessage = null;
let isSending = false;

// 서버에서 이 시간 동안 아무 데이터(status/delta 등)도 오지 않으면 "멈춘 것"으로
// 간주하고 요청을 중단한다. 백엔드가 첫 status를 즉시 보내므로, 이 값은 이후
// 노드 전환(라우팅→검색→응답 LLM 첫 토큰) 사이 최대 무응답 허용 시간이다.
// (LLM timeout=30s + 재시도를 고려해 넉넉히 잡음. 백엔드 하트비트 도입 시 낮출 수 있다.)
const STALL_TIMEOUT_MS = 60000;

// 체크포인터가 session_id(=thread_id) 별로 대화를 기억하므로, 브라우저 탭마다
// 고유한 값을 하나 만들어 재사용한다. 안 보내면 서버 기본값("default")을
// 모든 사용자가 공유하게 되어 대화가 서로 섞인다.
function createSessionId() {
    if (
        window.crypto &&
        typeof window.crypto.randomUUID === "function"
    ) {
        return window.crypto.randomUUID();
    }

    return `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getSessionId() {
    const key = "gachon_chat_session_id";
    let id = sessionStorage.getItem(key);

    if (!id) {
        id = createSessionId();
        sessionStorage.setItem(key, id);
    }

    return id;
}

const sessionId = getSessionId();

if (!chatForm || !messageInput || !chatBox || !sendButton) {
    console.error("필수 DOM 요소를 찾지 못했습니다.", {
        chatForm,
        messageInput,
        chatBox,
        sendButton,
    });
}

function setControlsDisabled(disabled) {
    sendButton.disabled = disabled;
    messageInput.disabled = disabled;

    quickQuestions.forEach((btn) => {
        btn.disabled = disabled;
    });
}

function nowText() {
    const now = new Date();
    return now.toLocaleTimeString("ko-KR", {
        hour: "2-digit",
        minute: "2-digit",
    });
}

function scrollToBottom() {
    chatBox.scrollTop = chatBox.scrollHeight;
}

function createMessageElement(sender) {
    const messageDiv = document.createElement("div");
    messageDiv.classList.add("message");

    if (sender === "user") {
        messageDiv.classList.add("user-message");
    } else {
        messageDiv.classList.add("bot-message");
    }

    return messageDiv;
}

function createBotAvatar() {
    const avatar = document.createElement("img");
    avatar.src = "/static/img/mascot.png";
    avatar.alt = "가천이";
    avatar.classList.add("avatar");
    return avatar;
}

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

// 봇 답변을 안전하게 HTML로 변환한다. XSS를 막기 위해 먼저 전부 escape 하고,
// URL 부분만 <a>로 되살린다(scheme을 http/https로 한정 → javascript: 차단).
// **굵게** 는 링크를 만든 뒤에 치환한다(URL 안의 * 오검출 방지).
function renderRichText(text) {
    const urlRe = /(https?:\/\/[^\s<]+[^\s<.,)])/g;
    let html = "";
    let last = 0;
    let match;

    while ((match = urlRe.exec(text)) !== null) {
        html += escapeHtml(text.slice(last, match.index));
        const url = match[0];
        html +=
            `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">` +
            `${escapeHtml(url)}</a>`;
        last = urlRe.lastIndex;
    }
    html += escapeHtml(text.slice(last));

    return html.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
}

// 답변 전(분석/검색 중) 진행 표시: 타이핑 점 애니메이션 + 상태 문구.
function pendingHtml(message) {
    return (
        '<span class="typing-dot"></span>' +
        '<span class="typing-dot"></span>' +
        '<span class="typing-dot"></span> ' +
        escapeHtml(message)
    );
}

// 오류/타임아웃 시 안내 문구와 "다시 시도" 버튼을 버블에 표시한다.
// 재시도는 실패한 봇 메시지를 지우고 같은 질문을 다시 보낸다(사용자 말풍선은
// 중복 추가하지 않도록 isRetry=true로 호출).
function showRetry(messageDiv, wrap, bubble, message, originalMessage) {
    bubble.textContent = message;

    const retry = document.createElement("button");
    retry.type = "button";
    retry.classList.add("retry-button");
    retry.textContent = "다시 시도";
    retry.addEventListener(
        "click",
        () => {
            if (isSending) {
                return;
            }
            messageDiv.remove();
            sendMessage(originalMessage, true);
        },
        { once: true }
    );

    wrap.appendChild(retry);
    scrollToBottom();
}

function addUserMessage(text) {
    const messageDiv = createMessageElement("user");

    const wrap = document.createElement("div");
    wrap.classList.add("bubble-wrap");

    const bubble = document.createElement("div");
    bubble.classList.add("bubble");
    bubble.textContent = text;

    const time = document.createElement("span");
    time.classList.add("timestamp");
    time.textContent = nowText();

    wrap.appendChild(bubble);
    wrap.appendChild(time);
    messageDiv.appendChild(wrap);
    chatBox.appendChild(messageDiv);
    scrollToBottom();
}

function addBotMessage(text, options = {}) {
    const messageDiv = createMessageElement("bot");
    messageDiv.appendChild(createBotAvatar());

    const wrap = document.createElement("div");
    wrap.classList.add("bubble-wrap");

    const bubble = document.createElement("div");
    bubble.classList.add("bubble");
    bubble.innerHTML = renderRichText(text);

    wrap.appendChild(bubble);

    if (options.sources && options.sources.length > 0) {
        appendSources(wrap, options.sources);
    }

    const time = document.createElement("span");
    time.classList.add("timestamp");
    time.textContent = nowText();
    wrap.appendChild(time);

    messageDiv.appendChild(wrap);
    chatBox.appendChild(messageDiv);
    scrollToBottom();

    return messageDiv;
}

function createStreamingBotMessage() {
    const messageDiv = createMessageElement("bot");
    messageDiv.appendChild(createBotAvatar());

    const wrap = document.createElement("div");
    wrap.classList.add("bubble-wrap");

    const bubble = document.createElement("div");
    bubble.classList.add("bubble");
    bubble.innerHTML = pendingHtml("질문을 분석하는 중이에요.");

    wrap.appendChild(bubble);
    messageDiv.appendChild(wrap);
    chatBox.appendChild(messageDiv);
    scrollToBottom();

    return { messageDiv, wrap, bubble };
}

function showLoading() {
    const messageDiv = createMessageElement("bot");
    messageDiv.appendChild(createBotAvatar());

    const wrap = document.createElement("div");
    wrap.classList.add("bubble-wrap");

    const bubble = document.createElement("div");
    bubble.classList.add("bubble");
    bubble.innerHTML = `<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span> 자료를 찾고 답변을 정리하는 중이에요.`;

    wrap.appendChild(bubble);
    messageDiv.appendChild(wrap);

    loadingMessage = messageDiv;
    chatBox.appendChild(messageDiv);
    scrollToBottom();
}

function hideLoading() {
    if (loadingMessage) {
        loadingMessage.remove();
        loadingMessage = null;
    }
}

async function sendMessage(message, isRetry = false) {
    const trimmed = message.trim();

    if (!trimmed || isSending) {
        return;
    }

    isSending = true;
    setControlsDisabled(true);

    // 재시도는 기존 사용자 말풍선/입력값을 그대로 두고 봇 응답만 다시 받는다.
    if (!isRetry) {
        addUserMessage(trimmed);
        messageInput.value = "";
        messageInput.style.height = "auto"; // 전송 후 한 줄 높이로 복귀
    }

    const { messageDiv, wrap, bubble } = createStreamingBotMessage();

    let meta = null;
    let buffer = "";
    let answerText = "";
    let hasStartedAnswer = false;
    let hasFinished = false;

    // 스톨(무응답) 감지: 일정 시간 데이터가 안 오면 요청을 중단해 무한 대기를
    // 명확한 오류로 전환한다. 데이터를 받을 때마다 타이머를 리셋한다.
    const controller = new AbortController();
    let stalled = false;
    let stallTimer = null;

    const armStall = () => {
        if (stallTimer) {
            clearTimeout(stallTimer);
        }
        stallTimer = setTimeout(() => {
            stalled = true;
            controller.abort();
        }, STALL_TIMEOUT_MS);
    };
    const clearStall = () => {
        if (stallTimer) {
            clearTimeout(stallTimer);
            stallTimer = null;
        }
    };

    try {
        armStall(); // fetch 응답 자체가 안 와도 중단되도록 먼저 무장

        const response = await fetch("/api/chat/stream", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ message: trimmed, session_id: sessionId }),
            signal: controller.signal,
        });

        if (!response.ok || !response.body) {
            throw new Error("스트리밍 응답 오류");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");

        while (true) {
            const { value, done } = await reader.read();

            if (done) {
                break;
            }

            armStall(); // 데이터 수신 → 타이머 리셋

            buffer += decoder.decode(value, { stream: true });

            const events = buffer.split("\n\n");
            buffer = events.pop();

            for (const rawEvent of events) {
                const parsed = parseSseEvent(rawEvent);

                if (!parsed) {
                    continue;
                }

                if (parsed.event === "status") {
                    if (!hasStartedAnswer) {
                        bubble.innerHTML = pendingHtml(parsed.data.message || "처리 중이에요.");
                    }
                }

                if (parsed.event === "meta") {
                    // 진행 표시(타이핑 점)는 첫 delta에서 지운다. 여기선 유지.
                    meta = parsed.data;
                }

                if (parsed.event === "delta") {
                    if (!hasStartedAnswer) {
                        bubble.textContent = "";
                        hasStartedAnswer = true;
                    }

                    // 스트리밍 중에는 평문으로 누적(부분 URL/**가 깨져 보이지 않게).
                    // 최종 렌더링(링크·굵게)은 done에서 한 번에 처리한다.
                    answerText += parsed.data.text || "";
                    bubble.textContent = answerText;
                    scrollToBottom();
                }

                if (parsed.event === "error") {
                    bubble.textContent = parsed.data.message || "스트리밍 중 오류가 발생했어요.";
                    hasFinished = true;
                    clearStall(); // 종료 신호 수신 → 잔여 대기로 인한 오탐 방지
                }

                if (parsed.event === "done") {
                    if (answerText) {
                        bubble.innerHTML = renderRichText(answerText);
                    }

                    if (meta && meta.sources && meta.sources.length > 0) {
                        appendSources(wrap, meta.sources);
                    }

                    appendTimestampOnce(wrap);
                    hasFinished = true;
                    clearStall(); // 종료 신호 수신 → 잔여 대기로 인한 오탐 방지
                    scrollToBottom();
                }
            }
        }

        clearStall();

        if (!hasFinished) {
            appendTimestampOnce(wrap);
        }
    } catch (error) {
        clearStall();
        const errorMessage = stalled
            ? "응답이 지연되어 요청을 중단했어요. 잠시 후 다시 시도해 주세요."
            : "오류가 발생했어요. 서버 상태, DB 연결, API Key를 확인해주세요.";
        showRetry(messageDiv, wrap, bubble, errorMessage, trimmed);
        console.error(error);
    } finally {
        clearStall();
        isSending = false;
        setControlsDisabled(false);
        messageInput.focus();
    }
}

function parseSseEvent(rawEvent) {
    const lines = rawEvent.split("\n");

    let event = "message";
    const dataLines = [];

    lines.forEach((line) => {
        const cleanLine = line.replace(/\r$/, "");

        if (cleanLine.startsWith("event:")) {
            event = cleanLine.slice(6).trim();
        }

        if (cleanLine.startsWith("data:")) {
            dataLines.push(cleanLine.slice(5).trimStart());
        }
    });

    if (dataLines.length === 0) {
        return null;
    }

    const dataText = dataLines.join("\n");

    try {
        return {
            event,
            data: JSON.parse(dataText),
        };
    } catch (error) {
        console.error("SSE parse error", error, rawEvent);
        return null;
    }
}

function appendSources(wrap, sources) {
    if (!sources || sources.length === 0) {
        return;
    }

    if (wrap.querySelector(".sources-box")) {
        return;
    }

    const sourcesBox = document.createElement("div");
    sourcesBox.classList.add("sources-box");

    const title = document.createElement("div");
    title.classList.add("sources-title");
    title.textContent = "참고한 자료";
    sourcesBox.appendChild(title);

    sources.forEach((source, index) => {
        const item = document.createElement("div");
        item.classList.add("source-item");

        const sourceName = source.source || source.title || "출처 없음";
        const page = source.page || source.source_page || "";
        const score = source.score !== undefined
            ? ` · 관련도 ${(Number(source.score) * 100).toFixed(1)}%`
            : "";

        item.textContent = `${index + 1}. ${sourceName}${page ? ` / ${page}` : ""}${score}`;
        sourcesBox.appendChild(item);
    });

    wrap.appendChild(sourcesBox);
}

function appendTimestampOnce(wrap) {
    if (wrap.querySelector(".timestamp")) {
        return;
    }

    const time = document.createElement("span");
    time.classList.add("timestamp");
    time.textContent = nowText();
    wrap.appendChild(time);
}

chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await sendMessage(messageInput.value);
});

// textarea 자동 높이 조절: 내용에 맞춰 늘리되 CSS max-height까지만(그 이상은 스크롤).
function autoGrowInput() {
    messageInput.style.height = "auto";
    messageInput.style.height = `${messageInput.scrollHeight}px`;
}
messageInput.addEventListener("input", autoGrowInput);

// Enter=전송, Shift+Enter=줄바꿈. 한글 등 IME 조합 중 Enter(조합 확정)는
// 전송으로 새면 안 되므로 isComposing(구형 브라우저는 keyCode 229)로 가드한다.
messageInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey) {
        return;
    }
    if (event.isComposing || event.keyCode === 229) {
        return;
    }
    event.preventDefault();
    chatForm.requestSubmit();
});

quickQuestions.forEach((button) => {
    button.addEventListener("click", async () => {
        const question = button.dataset.question || button.textContent;

        // data-prefill 버튼(예: 리마인드 예약)은 개인정보(이메일)를 사용자가 직접
        // 채워야 하므로 바로 전송하지 않고 입력창에 예시를 넣어 편집하게 한다.
        if (button.dataset.prefill === "true") {
            messageInput.value = question;
            autoGrowInput();
            messageInput.focus();
            const end = messageInput.value.length;
            messageInput.setSelectionRange(end, end);
            return;
        }

        await sendMessage(question);
    });
});
