from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import streamlit as st


def now_label() -> str:
    return datetime.now().strftime("%H:%M")


def new_conversation(title: str = "새 식단 상담") -> dict:
    return {
        "id": uuid4().hex,
        "title": title,
        "messages": [],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }


def init_state() -> None:
    if "conversations" not in st.session_state:
        first = new_conversation()
        st.session_state.conversations = [first]
        st.session_state.active_conversation_id = first["id"]
    if "is_generating" not in st.session_state:
        st.session_state.is_generating = False


def get_active_conversation() -> dict:
    conversations = st.session_state.conversations
    active_id = st.session_state.active_conversation_id
    for conversation in conversations:
        if conversation["id"] == active_id:
            return conversation

    st.session_state.active_conversation_id = conversations[0]["id"]
    return conversations[0]


def create_new_chat() -> None:
    """새 채팅 시작. 대화는 항상 하나만 유지한다(기존 대화는 지운다).

    로그인/장기기억이 없는 MVP라 여러 대화를 쌓아두지 않는다. '새 채팅'은
    깨끗한 새 상담으로 리셋하는 동작. 알레르기 프로필(user_allergies)은 전역이라 유지된다.
    """
    conversation = new_conversation()
    st.session_state.conversations = [conversation]
    st.session_state.active_conversation_id = conversation["id"]


def select_conversation(conversation_id: str) -> None:
    st.session_state.active_conversation_id = conversation_id


def update_conversation_title(conversation: dict, user_text: str) -> None:
    if conversation["messages"]:
        return

    compact = " ".join(user_text.split())
    if not compact:
        return

    conversation["title"] = compact[:24] + ("..." if len(compact) > 24 else "")


def append_message(
    conversation: dict,
    role: str,
    content: str,
    *,
    attachments: list[str] | None = None,
    agent_payload: dict | None = None,
) -> dict:
    message = {
        "id": uuid4().hex,
        "role": role,
        "content": content,
        "attachments": attachments or [],
        "agent": agent_payload,
        "created_at": now_label(),
    }
    conversation["messages"].append(message)
    conversation["updated_at"] = datetime.now().isoformat()
    return message
