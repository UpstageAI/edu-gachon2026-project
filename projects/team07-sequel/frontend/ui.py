import os
import httpx
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")
SYNC_ENDPOINT = f"{BACKEND_URL}/api/v1/chat/sync"

st.set_page_config(page_title="Medical QA Agent", layout="wide")
st.title("Medical QA Agent")
st.caption("의료 건강 정보에 대해 질문해 보세요.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("의료 관련 질문을 입력하세요"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("답변 생성 중..."):
            try:
                resp = httpx.post(SYNC_ENDPOINT, json={"message": prompt}, timeout=60.0)
                resp.raise_for_status()
                answer = resp.json().get("answer", "")
            except Exception as e:
                # 실습 편의를 위해 에러 내용을 그대로 표시합니다.
                # 실제 서비스에서는 사용자 친화적 메시지로 변환하세요.
                answer = f"오류: {e}"
        st.markdown(answer)
        st.session_state.messages.append({"role": "assistant", "content": answer})
