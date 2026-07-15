"""푸드 나침반 - 로컬 테스트용 Streamlit 챗봇 프론트엔드.

실행: streamlit run frontend/app.py
"""
import html
import json
import os

import httpx
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

_REGION_OPTIONS = ["강원도", "경기도", "경상도", "서울", "인천", "전라도", "제주도", "충청도"]
_UNIT_OPTIONS = ["100g", "500g", "1kg"]

_INTRO_MESSAGES = [
    {"role": "assistant", "content": "안녕하세요! 자취생 물가 지킴이, 푸드 나침반이에요 🧭"},
    {"role": "assistant", "content": "요즘 장바구니 물가 궁금하지 않으세요? 아래에서 지역과 단위를 선택해주세요!"},
]

st.set_page_config(page_title="Food Compass", page_icon="🛒")
st.title("🛒 Food Compass")

# 좌우로 나뉜 말풍선을 위한 커스텀 CSS
st.markdown(
    """
    <style>
    .bubble-row {
        display: flex;
        width: 100%;
        margin: 6px 0;
    }
    .bubble-row.user { justify-content: flex-end; }
    .bubble-row.assistant { justify-content: flex-start; }

    .bubble {
        max-width: 70%;
        padding: 10px 14px;
        border-radius: 16px;
        line-height: 1.5;
        font-size: 15px;
        word-wrap: break-word;
        white-space: pre-wrap;
    }
    .bubble.user {
        background-color: #87CEEB;
        color: #FFFFFF;
        border-bottom-right-radius: 4px;
    }
    .bubble.assistant {
        background-color: #F1F1F3;
        color: #000000;
        border-bottom-left-radius: 4px;
    }
    .bubble.status {
        background-color: #F1F1F3;
        color: #888888;
        font-style: italic;
        border-bottom-left-radius: 4px;
    }
    .bubble.error {
        background-color: #FFE2E2;
        color: #B00020;
        border-bottom-left-radius: 4px;
    }
    .bubble.confirm {
        background-color: #E6F4EA;
        color: #1E7B34;
        border-bottom-left-radius: 4px;
    }

    /* 인트로 말풍선 등장 애니메이션 (아래 -> 위 슬라이드 + 페이드인) */
    @keyframes slideUpFadeIn {
        from {
            opacity: 0;
            transform: translateY(16px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    .bubble-row.slide-up {
        animation: slideUpFadeIn 0.4s ease-out;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_bubble(role: str, content: str, variant: str = "", extra_class: str = ""):
    """role에 맞춰 좌/우 정렬된 말풍선 HTML을 그린다."""
    css_class = variant or role
    row_class = f"{role} {extra_class}".strip()
    safe_content = html.escape(content).replace("\n", "<br>")
    st.markdown(
        f'<div class="bubble-row {row_class}"><div class="bubble {css_class}">{safe_content}</div></div>',
        unsafe_allow_html=True,
    )


# 대화 기록 저장 (새로고침 전까지 유지됨) - 인트로 말풍선 2개를 처음부터 포함시켜서
# 별도 if/else 분기 없이 아래 단일 루프에서만 렌더링되도록 통일
if "messages" not in st.session_state:
    st.session_state.messages = list(_INTRO_MESSAGES)

# 인트로 애니메이션은 세션당 정확히 한 번만 재생됨. True로 바뀐 뒤로는 어떤 요소에도
# slide-up 클래스가 다시 붙지 않으므로, 리런이 몇 번 반복돼도 애니메이션이 재생될 수 없음.
if "intro_animated" not in st.session_state:
    st.session_state.intro_animated = False

if "selected_region" not in st.session_state:
    st.session_state.selected_region = None

if "selected_unit" not in st.session_state:
    st.session_state.selected_unit = None

if "selection_confirmed" not in st.session_state:
    st.session_state.selection_confirmed = False

# 대화 내용 출력 (인트로 2개는 최초 1회만 slide-up 애니메이션 적용, 확인 메시지도
# 이 리스트에 포함되어 자연스럽게 대화의 일부로 이어짐)
for i, msg in enumerate(st.session_state.messages):
    if not st.session_state.intro_animated and i < len(_INTRO_MESSAGES):
        render_bubble(msg["role"], msg["content"], variant=msg.get("variant", ""), extra_class="slide-up")
    else:
        render_bubble(msg["role"], msg["content"], variant=msg.get("variant", ""))

if not st.session_state.intro_animated:
    st.session_state.intro_animated = True

# 지역/단위 선택 UI는 아직 확인 전일 때만 보여줌 — 한 번 확인하고 나면 이 블록
# 전체가 다시는 렌더링되지 않아서, 그 뒤로는 순수 대화(채팅)만 이어지는 화면이 됨.
if not st.session_state.selection_confirmed:
    region = st.selectbox(
        "지역을 선택해주세요",
        _REGION_OPTIONS,
        index=None,
        placeholder="지역을 선택해주세요",
        key="region_select",
    )
    if region:
        st.session_state.selected_region = region

    # 지역이 선택된 경우에만 단위 selectbox 노출
    if st.session_state.selected_region:
        unit = st.selectbox(
            "단위를 선택해주세요",
            _UNIT_OPTIONS,
            index=None,
            placeholder="단위를 선택해주세요",
            key="unit_select",
        )
        if unit:
            st.session_state.selected_unit = unit

    selection_ready = bool(st.session_state.selected_region and st.session_state.selected_unit)

    if selection_ready:
        if st.button("선택 완료", type="primary"):
            st.session_state.selection_confirmed = True
            # 확인 메시지를 대화 기록에 정식으로 추가 — 이후로는 selectbox 블록이
            # 다시 렌더링되지 않으니 이 메시지가 대화의 자연스러운 다음 턴이 됨
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": (
                        f"{st.session_state.selected_region} · {st.session_state.selected_unit} "
                        "기준으로 답변해드려요! 이제 질문해주세요. (예. 상추 지금 비싸?)"
                    ),
                    "variant": "confirm",
                }
            )
            st.rerun()
    else:
        st.info("지역과 단위를 모두 선택해야 질문을 입력할 수 있어요.")

chat_ready = st.session_state.selection_confirmed

# 사용자 입력창 (하단 고정) - 선택 완료 버튼을 누르기 전까지 비활성화
query = st.chat_input(
    f"{st.session_state.selected_region} · {st.session_state.selected_unit} 기준으로 질문해보세요!"
    if chat_ready
    else "지역과 단위를 선택하고 '선택 완료'를 눌러주세요.",
    disabled=not chat_ready,
)

if query:
    # 사용자 메시지 표시 + 기록 저장
    st.session_state.messages.append({"role": "user", "content": query})
    render_bubble("user", query)

    # AI 응답 자리 (스트리밍 중 계속 갱신됨)
    status_placeholder = st.empty()
    answer_placeholder = st.empty()
    final_answer = ""

    try:
        # [2026-07-15 수정] router→validate_request→judge_price→generate_answer로 이어지는
        # LLM 호출 체인이 느려질 때(백업 모델 폴백 등) 기존 30초로는 부족해 실제로
        # httpx.ReadTimeout이 발생한 것을 사용자 재현으로 확인 — 여유를 두고 60초로 상향.
        with httpx.stream(
            "POST",
            f"{BACKEND_URL}/chat",
            json={
                "query": query,
                "region": st.session_state.selected_region,
                "unit": st.session_state.selected_unit,
            },
            timeout=60,
        ) as response:
            event_type = None
            for line in response.iter_lines():
                if not line:
                    continue
                if line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data = json.loads(line.split(":", 1)[1].strip())
                    if event_type == "status":
                        with status_placeholder:
                            render_bubble("assistant", data["step"], variant="status")
                    elif event_type == "result":
                        status_placeholder.empty()
                        final_answer = data["answer"]
                        with answer_placeholder:
                            render_bubble("assistant", final_answer)
    except httpx.ConnectError:
        status_placeholder.empty()
        final_answer = "⚠️ 백엔드 서버에 연결할 수 없습니다. uvicorn 서버가 실행 중인지 확인해주세요."
        with answer_placeholder:
            render_bubble("assistant", final_answer, variant="error")
    except httpx.TimeoutException:
        # [2026-07-15 추가] 응답이 오래 걸려 타임아웃되는 경우 — ConnectError와 원인이
        # 달라 별도 안내 문구로 분리(서버가 아예 꺼진 게 아니라 지연된 것뿐이므로).
        status_placeholder.empty()
        final_answer = "⚠️ 서버 응답이 지연되고 있어요. 잠시 후 다시 시도해주세요."
        with answer_placeholder:
            render_bubble("assistant", final_answer, variant="error")
    except Exception as e:
        # [2026-07-15 추가] 예상 못 한 예외가 Streamlit 화면에 원문 트레이스백 그대로
        # 노출되는 것을 막기 위한 최종 방어선 — 사용자에게는 "오류가 발생했다"는 사실만
        # 안내하고, 실제 원인은 서버 콘솔 로그에만 남긴다(§0-1과 별개로, 사용자 대면
        # 화면에는 내부 구현 세부사항을 노출하지 않는다는 원칙).
        print(f"[frontend] /chat 요청 중 예상치 못한 오류: {type(e).__name__}: {e}")
        status_placeholder.empty()
        final_answer = "⚠️ 일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요."
        with answer_placeholder:
            render_bubble("assistant", final_answer, variant="error")

    # AI 메시지도 기록에 저장 (다음 렌더링에서도 계속 보이도록)
    st.session_state.messages.append({"role": "assistant", "content": final_answer})