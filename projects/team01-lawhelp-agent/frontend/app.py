"""생활법률 안내 챗봇 Streamlit 최소 UI (파트B Day3 작업 5).

SSE 이벤트 계약 (파트 A와 확정, 파트B_DAY3_작업지시 8절):
- token: data {"text": "..."} 를 이어붙여 실시간 표시
- done:  data {} 고정. 수신 루프 종료
- error: data {"message": "..."}. 그 자체로 스트림 종료 신호 (done을 기다리지 않는다)

파트 A의 /chat/stream merge 전에는 USE_STREAM=false 로 /chat/sync 임시 검증.
대화 목록은 화면 표시용으로만 st.session_state에 유지한다 (서버 전송·저장 없음).

실행: streamlit run frontend/app.py
"""

import json
import os

import requests
import streamlit as st

API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")
USE_STREAM = os.environ.get("USE_STREAM", "true").lower() != "false"

DISCLAIMER = "본 서비스는 일반 정보 제공이며 법률 자문이 아닙니다."
CONNECT_ERROR_MESSAGE = "서버에 연결할 수 없습니다. API 서버가 실행 중인지 확인해 주세요."


def iter_sse_events(message: str):
    """/chat/stream을 호출해 (event, data) 튜플을 순차 반환한다.

    수신 루프 종료 조건: done 수신 OR error 수신 OR 연결 종료.
    """
    with requests.post(
        f"{API_BASE}/chat/stream",
        json={"message": message},
        stream=True,
        timeout=(5, 120),
    ) as response:
        response.raise_for_status()
        event = None
        for raw_line in response.iter_lines(decode_unicode=True):
            line = (raw_line or "").strip()
            if not line:
                event = None  # 빈 줄 = 이벤트 블록 경계
                continue
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                payload = line.split(":", 1)[1].strip()
                try:
                    data = json.loads(payload) if payload else {}
                except json.JSONDecodeError:
                    data = {}
                yield event, data
                if event in ("done", "error"):
                    return


def ask_stream(message: str, placeholder) -> str:
    """스트리밍 모드: token을 이어붙여 실시간 갱신, error는 즉시 종료."""
    answer = ""
    for event, data in iter_sse_events(message):
        if event == "token":
            answer += data.get("text", "")
            placeholder.write(answer)
        elif event == "done":
            break
        elif event == "error":
            answer = f"오류가 발생했습니다: {data.get('message', '알 수 없는 오류')}"
            placeholder.error(answer)
            break
    return answer


def ask_sync(message: str, placeholder) -> str:
    """임시 검증 모드: /chat/sync로 answer를 한 번에 표시."""
    response = requests.post(
        f"{API_BASE}/chat/sync", json={"message": message}, timeout=60
    )
    response.raise_for_status()
    answer = response.json()["answer"]
    placeholder.write(answer)
    return answer


st.title("생활법률 안내 챗봇")
st.caption(DISCLAIMER)

if "messages" not in st.session_state:
    st.session_state.messages = []

for past in st.session_state.messages:
    with st.chat_message(past["role"]):
        st.write(past["content"])

question = st.chat_input("생활법률 질문을 입력해 주세요")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        try:
            if USE_STREAM:
                answer = ask_stream(question, placeholder)
            else:
                answer = ask_sync(question, placeholder)
        except requests.RequestException:
            answer = CONNECT_ERROR_MESSAGE
            placeholder.error(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})
