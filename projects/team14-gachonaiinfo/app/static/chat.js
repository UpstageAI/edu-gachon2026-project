const chatForm = document.getElementById("chat-form");
const messageInput = document.getElementById("message-input");
const chatBox = document.getElementById("chat-box");
const sendButton = document.getElementById("send-button");
const quickQuestions = document.querySelectorAll(".quick-question");

let loadingMessage = null;
let isSending = false;

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
    bubble.textContent = text;

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
    bubble.textContent = "질문을 분석하는 중이에요.";

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

async function sendMessage(message) {
    const trimmed = message.trim();

    if (!trimmed || isSending) {
        return;
    }

    isSending = true;
    setControlsDisabled(true);

    addUserMessage(trimmed);
    messageInput.value = "";
    messageInput.style.height = "auto"; // 전송 후 한 줄 높이로 복귀

    const { wrap, bubble } = createStreamingBotMessage();

    let meta = null;
    let buffer = "";
    let hasStartedAnswer = false;
    let hasFinished = false;

    try {
        const response = await fetch("/api/chat/stream", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ message: trimmed, session_id: sessionId }),
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
                        bubble.textContent = parsed.data.message || "처리 중이에요.";
                    }
                }

                if (parsed.event === "meta") {
                    meta = parsed.data;
                    bubble.textContent = "";
                }

                if (parsed.event === "delta") {
                    if (!hasStartedAnswer) {
                        bubble.textContent = "";
                        hasStartedAnswer = true;
                    }

                    bubble.textContent += parsed.data.text || "";
                    scrollToBottom();
                }

                if (parsed.event === "error") {
                    bubble.textContent = parsed.data.message || "스트리밍 중 오류가 발생했어요.";
                    hasFinished = true;
                }

                if (parsed.event === "done") {
                    if (meta && meta.sources && meta.sources.length > 0) {
                        appendSources(wrap, meta.sources);
                    }

                    appendTimestampOnce(wrap);
                    hasFinished = true;
                    scrollToBottom();
                }
            }
        }

        if (!hasFinished) {
            appendTimestampOnce(wrap);
        }
    } catch (error) {
        bubble.textContent = "오류가 발생했어요. 서버 상태, DB 연결, API Key를 확인해주세요.";
        appendTimestampOnce(wrap);
        console.error(error);
    } finally {
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
            ? ` · 관련도 ${Number(source.score).toFixed(3)}`
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
        await sendMessage(question);
    });
});
