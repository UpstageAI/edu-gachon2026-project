from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

FRONTEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = FRONTEND_DIR.parent
for import_path in (str(PROJECT_ROOT), str(FRONTEND_DIR)):
    if import_path in sys.path:
        sys.path.remove(import_path)
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(1, str(FRONTEND_DIR))

from api_client import stream_recommendation  # noqa: E402
from auth_view import render_login_entry  # noqa: E402
from chat_state import (  # noqa: E402
    append_message,
    get_active_conversation,
    init_state,
    update_conversation_title,
)
from chat_view import (  # noqa: E402
    render_empty_state,
    render_message,
    render_message_stream_spacer,
    render_progress_step,
    render_suggestion_buttons,
)
from composer import render_chat_composer, reset_attachment_widget  # noqa: E402
from sidebar import render_sidebar  # noqa: E402
from styles import inject_global_styles  # noqa: E402


st.set_page_config(
    page_title="Healthy Meal Agent",
    layout="wide",
    initial_sidebar_state="expanded",
)


def submit_user_message(text: str, attachments: list[str] | None = None) -> None:
    clean_text = text.strip()
    if not clean_text and not attachments:
        return

    conversation = get_active_conversation()
    display_text = clean_text or "첨부 파일을 기준으로 건강한 한 끼를 추천해줘"

    update_conversation_title(conversation, display_text)
    append_message(
        conversation,
        "user",
        display_text,
        attachments=attachments,
    )

    st.session_state.pending_user_message = display_text
    st.session_state.pending_had_attachments = bool(attachments)
    st.session_state.is_generating = True
    st.rerun()


inject_global_styles()
init_state()
st.session_state.setdefault("pending_user_message", "")
st.session_state.setdefault("pending_had_attachments", False)

with st.sidebar:
    render_sidebar()

render_login_entry()

active = get_active_conversation()
pending_user_message = st.session_state.get("pending_user_message", "")

queued_prompt: str | None = None
submitted_text = ""
submitted_files: list[str] = []

if not active["messages"]:
    with st.container(key="welcome_stage"):
        render_empty_state()
        submitted_text, submitted_files = render_chat_composer(
            disabled=st.session_state.is_generating,
            pinned=False,
        )
        queued_prompt = render_suggestion_buttons()
else:
    with st.container(key="conversation_shell"):
        with st.container(key="message_stream"):
            for message in active["messages"]:
                render_message(message)
            # 생성 중이면 여기(마지막 메시지 자리)에 실시간 단계 표시가 들어간다.
            progress_slot = st.empty() if pending_user_message else None
            render_message_stream_spacer()
    submitted_text, submitted_files = render_chat_composer(
        disabled=st.session_state.is_generating,
        pinned=True,
    )

if pending_user_message:
    # SSE로 파이프라인 단계를 실시간 수신 → 단계 문구를 갱신하다가, 결과가 오면 대화에 추가.
    assistant_text = "조건을 조금 더 알려주시면 식단을 다시 맞춰볼게요."
    agent_payload = None
    for kind, value in stream_recommendation(
        pending_user_message,
        allergies=st.session_state.get("user_allergies", []),
        thread_id=active["id"],
    ):
        if kind == "progress" and progress_slot is not None:
            with progress_slot:
                render_progress_step(value)
        elif kind == "result":
            assistant_text, agent_payload = value
        elif kind == "error":
            assistant_text, agent_payload = value, None
    if progress_slot is not None:
        progress_slot.empty()
    append_message(
        active,
        "assistant",
        assistant_text,
        agent_payload=agent_payload,
    )
    if st.session_state.get("pending_had_attachments"):
        reset_attachment_widget()
    st.session_state.pending_user_message = ""
    st.session_state.pending_had_attachments = False
    st.session_state.is_generating = False
    st.rerun()
elif queued_prompt:
    submit_user_message(queued_prompt)
elif submitted_text or submitted_files:
    submit_user_message(submitted_text, attachments=submitted_files)
