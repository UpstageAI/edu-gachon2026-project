from __future__ import annotations

import streamlit as st

from chat_state import create_new_chat, select_conversation


def render_sidebar_header() -> None:
    st.html(
        """
        <div class="sidebar-brand">
            <div>
                <div class="sidebar-title">Meal Agent</div>
            </div>
        </div>
        """,
    )


def format_conversation_title(conversation: dict) -> str:
    title = conversation["title"].strip() or "새 식단 상담"
    return title[:28] + ("..." if len(title) > 28 else "")


def render_allergy_profile() -> None:
    """알레르기·못 먹는 음식 입력. 세션 동안 유지되며 모든 추천에 반영된다.

    로그인이 없는 MVP라 브라우저 세션 단위로만 기억한다(기획서: 세션 간 장기기억은 비목표).
    새 채팅을 만들어도 이 프로필은 유지된다(session_state 전역).
    """
    st.html('<div class="sidebar-section-label">내 프로필</div>')
    raw = st.text_input(
        "알레르기·못 먹는 음식",
        key="profile_allergies_input",
        placeholder="예: 계란, 우유, 새우",
        help="쉼표로 구분해 입력하세요. 입력한 재료가 든 음식은 추천에서 제외됩니다.",
    )
    allergies = [x.strip() for x in raw.split(",") if x.strip()]
    st.session_state.user_allergies = allergies
    if allergies:
        st.html(
            '<div class="sidebar-empty">제외 중: ' + ", ".join(allergies) + "</div>",
        )


def render_sidebar() -> None:
    render_sidebar_header()

    if st.button(
        "새 채팅",
        key="sidebar_new_chat",
        icon=":material/add:",
        width="stretch",
    ):
        create_new_chat()
        st.rerun()

    render_allergy_profile()

    st.html('<div class="sidebar-section-label">최근</div>')

    # 대화는 항상 하나만 유지한다(새 채팅 시 기존 대화 삭제) → 검색 불필요.
    for conversation in st.session_state.conversations:
        label = format_conversation_title(conversation)
        is_active = conversation["id"] == st.session_state.active_conversation_id
        if st.button(
            label,
            key=f"conversation_{conversation['id']}",
            icon=":material/chat_bubble:",
            type="primary" if is_active else "secondary",
            width="stretch",
        ):
            if not is_active:
                select_conversation(conversation["id"])
                st.rerun()
