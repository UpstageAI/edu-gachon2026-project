# ui/gradio_app.py

from __future__ import annotations

import html
import sys
import time
from pathlib import Path

import gradio as gr


# ---------------------------------------------------------
# 프로젝트 루트를 Python 경로에 추가
# ---------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.agents.react_loop import stream_triproute_react_loop  # noqa: E402
from app.services import auth_client, chat_store  # noqa: E402
from app.services.upstage_client import stream_trip_summary  # noqa: E402
from app.utils.formatter import (  # noqa: E402
    format_condition_summary,
    format_cost_summary,
    format_daily_schedule,
    format_route_summary,
)


# ---------------------------------------------------------
# 로고 (좌측 상단). ui/assets/triproute_logo.png 에 로고 파일을 두면 표시된다.
# ---------------------------------------------------------
LOGO_PATH = PROJECT_ROOT / "ui" / "assets" / "triproute_logo.png"


# ---------------------------------------------------------
# 기본값
# ---------------------------------------------------------
DEFAULT_MESSAGE = (
    "강릉으로 1박 2일 여행 가고 싶어. "
    "바다랑 감성 카페, 먹거리를 좋아해."
)

WELCOME_MESSAGE = (
    "안녕하세요! <b>TripRoute AI 여행 플래너</b>입니다.<br><br>"
    "아래처럼 여행 조건을 자연어로 입력해주세요.<br><br>"
    "<span style='color:#8B8D98;'>&gt; 강릉으로 1박 2일 여행 가고 싶어.<br>"
    "&gt; 바다랑 감성 카페, 먹거리를 좋아해.</span><br><br>"
    "여행 계획이 완성되면 가운데 <b>결과 패널</b>에서 일정 · 동선 · 비용을 확인할 수 있어요.<br>"
    "로그인하면 대화 기록이 저장되고, \"카페 말고 맛집 위주로 바꿔줘\" 같은 후속 요청도<br>"
    "이전 조건을 이어받아 처리됩니다."
)

LOADING_MESSAGE = "여행 계획을 만들고 있어요..."

RESULT_PLACEHOLDER = (
    "아직 생성된 여행 계획이 없습니다.\n\n"
    "오른쪽 **요청사항**에서 여행 요청을 입력하고 **여행 계획 생성**을 눌러주세요."
)

LOGIN_ERROR_MESSAGE = "이메일 또는 비밀번호를 확인해주세요."
SIGNUP_PENDING_MESSAGE = (
    "가입 처리 중 문제가 발생했습니다. 이미 가입된 이메일이면 로그인해주세요."
)
EMPTY_AUTH_INPUT_MESSAGE = "이메일과 비밀번호를 입력해주세요."

# access_token 만료 이 시간(초) 전부터는 미리 refresh_token으로 갱신한다
TOKEN_REFRESH_MARGIN_SECONDS = 60

GUEST_BROWSER_STATE = {"refresh_token": None, "user_id": None, "email": None}


# ---------------------------------------------------------
# 다국어(i18n) — 설정 팝업의 "언어"로 전환되는 UI 문구
# ---------------------------------------------------------
I18N = {
    "ko": {
        "new_chat": "＋  새로운 대화",
        "recent": "이전 대화 기록",
        "search_ph": "이전 대화 검색",
        "req": "요청사항",
        "transport": "이동수단",
        "people": "여행 인원",
        "msg_label": "여행 요청",
        "msg_ph": "여행 지역, 기간, 취향을 입력해주세요.  예) " + DEFAULT_MESSAGE,
        "send": "여행 계획 생성",
        "logout": "로그아웃",
    },
    "en": {
        "new_chat": "＋  New chat",
        "recent": "Recent chats",
        "search_ph": "Search chats",
        "req": "Requests",
        "transport": "Transport",
        "people": "Travelers",
        "msg_label": "Trip request",
        "msg_ph": "Enter destination, dates, and preferences.  e.g. A 2-day trip to Gangneung",
        "send": "Generate plan",
        "logout": "Log out",
    },
}


# ---------------------------------------------------------
# 결과 패널 렌더링
# ---------------------------------------------------------
def _build_result_sections(result: dict):
    return (
        format_daily_schedule(result),
        format_route_summary(result),
        format_cost_summary(result),
        format_condition_summary(result),
    )


NO_RESULT_UPDATE = (
    gr.update(),
    gr.update(),
    gr.update(),
    gr.update(),
)

RESET_RESULT_TUPLE = (
    RESULT_PLACEHOLDER,
    RESULT_PLACEHOLDER,
    RESULT_PLACEHOLDER,
    RESULT_PLACEHOLDER,
)

# 로그인/회원가입 모달(auth_overlay, auth_modal)의 열림 상태를 그대로 둘지, 닫을지.
# 로그인/회원가입 성공 시에만 _MODAL_CLOSED를 써서 Python이 직접 닫는다 — 이전에는
# JS가 "logged-in-group이 렌더링됐는지"를 화면에서 측정해서 판단했는데, 타이밍에 따라
# 그 측정이 씹혀서 모달이 안 닫히고 빈 채로 남는 경우가 있었다.
_MODAL_UNCHANGED = (gr.update(), gr.update())
_MODAL_CLOSED = (gr.update(visible=False), gr.update(visible=False))


# ---------------------------------------------------------
# 로그인 상태 갱신/조회 헬퍼
# ---------------------------------------------------------
def _ensure_fresh_access_token(access_token_info, auth_state):
    """
    로그인 상태면 access_token 만료가 임박했는지 확인하고, 필요하면 refresh_token으로
    미리 갱신한다. Supabase는 refresh_token을 1회용으로 회전시키므로 새로 받은
    refresh_token을 auth_state(BrowserState)에도 같이 반영해야 다음 갱신이 안 깨진다.
    갱신에 실패하면 로그인이 만료된 것으로 보고 조용히 게스트 상태로 되돌린다.

    반환값: (access_token_info, auth_state, is_logged_in)
    """
    if not access_token_info or not access_token_info.get("access_token"):
        return None, auth_state, False

    if time.time() < access_token_info.get("expires_at", 0) - TOKEN_REFRESH_MARGIN_SECONDS:
        return access_token_info, auth_state, True

    refresh_token = (auth_state or {}).get("refresh_token")
    if not refresh_token:
        return None, dict(GUEST_BROWSER_STATE), False

    session = auth_client.refresh_session(refresh_token)
    if session is None or not session.get("access_token"):
        return None, dict(GUEST_BROWSER_STATE), False

    new_access_token_info = {
        "access_token": session["access_token"],
        "expires_at": time.time() + (session.get("expires_in") or 3600),
        "user_id": session["user_id"],
    }
    new_auth_state = {
        "refresh_token": session["refresh_token"],
        "user_id": session["user_id"],
        "email": session["email"],
    }
    return new_access_token_info, new_auth_state, True


def _session_label(session: dict) -> str:
    title = session.get("title")
    if title:
        return title

    summary = session.get("last_condition_summary") or {}
    city = summary.get("city")
    if city:
        return f"{city} 여행"

    return "새 대화"


def _session_choices(sessions):
    return [(_session_label(session), session["id"]) for session in sessions]


def _filter_session_choices(sessions, query):
    """검색어로 최근 대화 목록을 필터링해 Radio choices로 돌려준다."""
    query = (query or "").strip().lower()
    if not query:
        return _session_choices(sessions)
    return [
        (_session_label(s), s["id"])
        for s in sessions
        if query in _session_label(s).lower()
    ]


def search_sessions(query, sessions):
    return gr.update(choices=_filter_session_choices(sessions or [], query), value=None)


def _guest_ui_updates():
    return (
        gr.update(visible=True),   # logged_out_group
        gr.update(visible=False),  # logged_in_group
        "",                        # welcome_text
        gr.update(choices=[], value=None, visible=False),  # session_radio
        gr.update(visible=False),  # no_session_msg
        None,                      # access_token_state
        dict(GUEST_BROWSER_STATE),  # auth_browser_state
        [],                        # recent_sessions_state
        gr.update(visible=True),   # login_trigger_btn
    )


def _profile_html(email: str) -> str:
    safe_email = html.escape(email or "")
    display_name = html.escape((email or "여행자").split("@")[0])
    initial = html.escape(email[:1].upper()) if email else "U"
    return (
        "<div class='tr-profile'>"
        f"<div class='tr-avatar'>{initial}</div>"
        "<div class='tr-profile-meta'>"
        f"<div class='tr-profile-name'>{display_name}님</div>"
        f"<div class='tr-profile-email'>{safe_email}</div>"
        "</div></div>"
    )


def _logged_in_ui_updates(email, access_token, expires_at, user_id, sessions, refresh_token):
    has_sessions = len(sessions) > 0
    return (
        gr.update(visible=False),  # logged_out_group
        gr.update(visible=True),   # logged_in_group
        _profile_html(email),      # welcome_text
        gr.update(choices=_session_choices(sessions), value=None, visible=has_sessions),  # session_radio
        gr.update(visible=not has_sessions),  # no_session_msg
        {"access_token": access_token, "expires_at": expires_at, "user_id": user_id},
        {"refresh_token": refresh_token, "user_id": user_id, "email": email},
        sessions,
        gr.update(visible=False),  # login_trigger_btn — 로그인하면 사이드바에 최근 대화가 바로 보이니 필요 없음
    )


def sync_theme_radio(saved_theme):
    """
    테마 라디오는 컴포넌트 기본값("dark")으로만 초기 렌더링돼서, 라이트 모드를 고르고
    새로고침해도(APPLY_THEME_JS가 ?__theme= 쿼리로 리로드시킴) 라디오 자체는 계속
    "다크 모드"가 선택된 것처럼 보이고, 심지어 클릭해도 Gradio 내부 값이 이미 "dark"라고
    (착각)해서 반응이 없었다. gr.Request로 URL 쿼리를 직접 읽는 방식은 큐가 응답 없이
    멈추는 문제가 있어서, 이미 로그인 지속에 잘 쓰이고 있는 gr.BrowserState 패턴을
    그대로 재사용해 마지막으로 고른 테마를 localStorage에 저장/복원한다.
    """
    theme = saved_theme if saved_theme in ("dark", "light") else "dark"
    return gr.update(value=theme)


def save_theme(theme):
    """theme_radio 변경 시 gr.BrowserState(theme_browser_state)에 선택값을 저장한다."""
    return theme if theme in ("dark", "light") else "dark"


def restore_login(auth_state):
    """페이지 로드 시 BrowserState의 refresh_token으로 로그인 상태를 복구한다."""
    refresh_token = (auth_state or {}).get("refresh_token")

    if not refresh_token:
        return (*_guest_ui_updates(), "", *_MODAL_UNCHANGED)

    session = auth_client.refresh_session(refresh_token)

    if session is None or not session.get("access_token"):
        return (*_guest_ui_updates(), "", *_MODAL_UNCHANGED)

    expires_at = time.time() + (session.get("expires_in") or 3600)

    try:
        sessions = chat_store.list_recent_sessions(session["user_id"])
    except Exception:
        sessions = []

    return (
        *_logged_in_ui_updates(
            email=session["email"],
            access_token=session["access_token"],
            expires_at=expires_at,
            user_id=session["user_id"],
            sessions=sessions,
            refresh_token=session["refresh_token"],
        ),
        "",
        *_MODAL_UNCHANGED,
    )


def do_signup(email: str, password: str):
    email = (email or "").strip()
    password = password or ""

    if not email or not password:
        return (*_guest_ui_updates(), EMPTY_AUTH_INPUT_MESSAGE, *_MODAL_UNCHANGED)

    try:
        session = auth_client.sign_up(email, password)
    except auth_client.AuthError as error:
        return (*_guest_ui_updates(), f"회원가입 실패: {error}", *_MODAL_UNCHANGED)

    if not session.get("access_token"):
        return (*_guest_ui_updates(), SIGNUP_PENDING_MESSAGE, *_MODAL_UNCHANGED)

    expires_at = time.time() + (session.get("expires_in") or 3600)

    try:
        sessions = chat_store.list_recent_sessions(session["user_id"])
    except Exception:
        sessions = []

    return (
        *_logged_in_ui_updates(
            email=session["email"],
            access_token=session["access_token"],
            expires_at=expires_at,
            user_id=session["user_id"],
            sessions=sessions,
            refresh_token=session["refresh_token"],
        ),
        "",
        *_MODAL_CLOSED,
    )


def do_login(email: str, password: str):
    email = (email or "").strip()
    password = password or ""

    if not email or not password:
        return (*_guest_ui_updates(), EMPTY_AUTH_INPUT_MESSAGE, *_MODAL_UNCHANGED)

    try:
        session = auth_client.sign_in(email, password)
    except auth_client.AuthError:
        return (*_guest_ui_updates(), LOGIN_ERROR_MESSAGE, *_MODAL_UNCHANGED)

    if not session.get("access_token"):
        return (*_guest_ui_updates(), LOGIN_ERROR_MESSAGE, *_MODAL_UNCHANGED)

    expires_at = time.time() + (session.get("expires_in") or 3600)

    try:
        sessions = chat_store.list_recent_sessions(session["user_id"])
    except Exception:
        sessions = []

    return (
        *_logged_in_ui_updates(
            email=session["email"],
            access_token=session["access_token"],
            expires_at=expires_at,
            user_id=session["user_id"],
            sessions=sessions,
            refresh_token=session["refresh_token"],
        ),
        "",
        *_MODAL_CLOSED,
    )


def do_logout(access_token_info, auth_state):
    access_token = (access_token_info or {}).get("access_token")
    refresh_token = (auth_state or {}).get("refresh_token")

    if access_token and refresh_token:
        try:
            auth_client.sign_out(access_token, refresh_token)
        except auth_client.AuthError:
            pass

    return (
        *_guest_ui_updates(),
        "",
        *_MODAL_UNCHANGED,
        [{"role": "assistant", "content": WELCOME_MESSAGE}],
        "",
        None,
        None,
        None,
    )


def load_session(session_id, auth_browser_state):
    """
    사이드바 '최근 대화' 목록에서 세션을 선택하면 그 대화 기록을 불러온다.

    access_token_state/recent_sessions_state를 입력으로 받는 대신 auth_browser_state
    (user_id 포함)만으로 직접 조회한다 — do_login/do_signup처럼 실제 네트워크 I/O가 있는
    이벤트가 access_token_state/recent_sessions_state를 gr.BrowserState와 같은 출력
    배치에서 갱신하면, 이후 다른 이벤트(session_radio.change)에는 이 State들이 None으로
    넘어오는 문제가 있었다(원인을 좁혀봤지만 Gradio 6.20 자체의 동작으로 보이고 더 깊이
    파진 못했다). auth_browser_state는 이 문제 없이 항상 정상적으로 넘어와서 이걸로 대체.
    """
    user_id = (auth_browser_state or {}).get("user_id")

    if not session_id or not user_id:
        return (gr.update(),) * 5 + RESET_RESULT_TUPLE

    try:
        messages = chat_store.get_session_messages(session_id, user_id)
    except Exception:
        messages = []

    history = [
        {"role": message["role"], "content": message["content"]}
        for message in messages
    ]
    if not history:
        history = [{"role": "assistant", "content": WELCOME_MESSAGE}]

    try:
        sessions = chat_store.list_recent_sessions(user_id)
    except Exception:
        sessions = []

    session_row = next(
        (s for s in sessions if s.get("id") == session_id),
        None,
    )
    previous_condition = (session_row or {}).get("last_condition_summary")

    try:
        stored_result = chat_store.get_session_result(session_id, user_id)
    except Exception:
        stored_result = None

    result_sections = (
        _build_result_sections(stored_result) if stored_result else RESET_RESULT_TUPLE
    )

    return (history, "", previous_condition, stored_result, session_id, *result_sections)


# ---------------------------------------------------------
# 챗봇 메시지 처리 (제너레이터: 로딩 상태 → 최종 결과)
# ---------------------------------------------------------
def chat(
    message: str,
    history: list[dict[str, str]] | None,
    transport_mode: str,
    people_count: int | float,
    access_token_info,
    previous_condition,
    previous_result,
    active_session_id,
    auth_state,
):
    if history is None:
        history = []

    normalized_message = (message or "").strip()

    # "새 대화" 버튼(clear_chat)이 메시지를 보내기 전에 이미 제목 없는 세션을 미리
    # 만들어두므로, session_id의 신규 여부만으로는 "이 세션의 첫 메시지인지"를 알 수
    # 없다 — 화면에 표시된 이전 대화 중 사용자 메시지가 하나도 없으면 첫 메시지로 본다.
    is_first_message_in_session = not any(
        turn.get("role") == "user" for turn in history
    )

    # 사이드바 "최근 대화" 갱신 정보(session_radio, recent_sessions_state, no_session_msg) —
    # 새 세션이 생기거나 제목이 바뀌기 전까지는 그대로 두고(gr.update()), 실제로 목록이
    # 바뀌는 시점에만 새로 계산해서 덮어쓴다.
    sidebar_update = (gr.update(), gr.update(), gr.update())

    if not normalized_message:
        yield (
            history, "", *NO_RESULT_UPDATE,
            previous_condition, previous_result, active_session_id,
            access_token_info, auth_state, *sidebar_update,
        )
        return

    access_token_info, auth_state, is_logged_in = _ensure_fresh_access_token(
        access_token_info, auth_state
    )

    history = history + [{"role": "user", "content": normalized_message}]

    # 1) 스트리밍이 시작되기 전(첫 Solar 호출 전)에도 즉시 뭔가 보이도록 초기 로딩 상태를
    # 먼저 보여준다. 이후엔 단계별 진행 메시지(아래 for 루프)가 이 자리를 계속 갱신한다.
    loading_history = history + [
        {"role": "assistant", "content": LOADING_MESSAGE}
    ]
    yield (
        loading_history, "", *NO_RESULT_UPDATE,
        previous_condition, previous_result, active_session_id,
        access_token_info, auth_state, *sidebar_update,
    )

    session_id = active_session_id

    if is_logged_in:
        try:
            if session_id is None:
                session_row = chat_store.create_session(
                    access_token_info["user_id"],
                    title=normalized_message[:40],
                )
                session_id = session_row["id"]
                # 대화를 만들자마자(첫 응답이 나오기 한참 전이라도) 사이드바 "최근 대화"
                # 목록에 바로 보이도록 여기서 즉시 갱신한다 — 끝까지 기다렸다가 갱신하면
                # 생성 직후엔 목록에 안 보이는 문제가 있었음.
                sessions = chat_store.list_recent_sessions(access_token_info["user_id"])
                sidebar_update = (
                    gr.update(choices=_session_choices(sessions), visible=True),
                    sessions,
                    gr.update(visible=False),
                )
            chat_store.append_message(
                session_id, access_token_info["user_id"], "user", normalized_message
            )
        except Exception:
            pass

    # 2) 실제 계획 생성 — 노드가 끝날 때마다 진행 메시지를 받아 채팅 버블을 갱신한다.
    try:
        normalized_people_count = int(people_count)
        result = None

        for progress_message, maybe_result in stream_triproute_react_loop(
            user_input=normalized_message,
            transport_mode=transport_mode,
            people_count=normalized_people_count,
            previous_condition_summary=previous_condition,
            previous_result=previous_result,
            # 로그인 세션의 session_id를 그대로 체크포인트 thread_id로 재사용해서,
            # 같은 대화는 LangGraph 체크포인터에도 같은 단위로 쌓이게 한다.
            thread_id=session_id,
        ):
            progress_history = history + [
                {"role": "assistant", "content": progress_message}
            ]
            yield (
                progress_history, "", *NO_RESULT_UPDATE,
                previous_condition, previous_result, active_session_id,
                access_token_info, auth_state, *sidebar_update,
            )
            if maybe_result is not None:
                result = maybe_result

        result_sections = _build_result_sections(result)
        new_condition = result.get("condition_summary")

        city = new_condition.get("city", "알 수 없는 지역") if new_condition else "알 수 없는 지역"
        themes = new_condition.get("travel_style", []) if new_condition else []
        theme_str = ", ".join(themes) if themes else "일반"
        duration = new_condition.get("duration", "알 수 없는 기간") if new_condition else "알 수 없는 기간"

        header = (
            "요청하신 여행 계획 생성이 완료되었습니다! ✨<br><br>"
            f"✅ <b>장소:</b> {html.escape(city)}<br>"
            f"✅ <b>기간:</b> {html.escape(duration)}<br>"
            f"✅ <b>인원:</b> {normalized_people_count}명<br>"
            f"✅ <b>이동수단:</b> {transport_mode}<br>"
            f"✅ <b>테마:</b> {html.escape(theme_str)}<br><br>"
        )

        # 3) 자연어 설명 문단만 Solar stream=True로 타이핑 효과를 내며 이어붙인다.
        # daily_schedule/cost_summary 같은 계산된 수치 데이터는 이미 위에서 확정된
        # result_sections로 한 번에 표시되고, 스트리밍 대상이 아니다.
        #
        # output 가드레일: chatbot 말풍선은 HTML로 그대로 렌더링되므로(header가 이미
        # <b>/<br> 태그를 raw HTML로 씀), 사용자 입력 문구가 Solar 응답에 일부라도
        # 그대로 echo되면 XSS로 이어질 수 있다. streamed_text(LLM이 생성한 부분)만
        # html.escape()로 이스케이프하고, 우리가 직접 쓰는 고정 문구(header, 아래
        # 실패 시 fallback 문구)의 의도된 태그는 그대로 유지한다.
        streamed_text = ""
        used_fallback_reason = False
        try:
            for delta in stream_trip_summary(
                new_condition, result["daily_schedule"], result["cost_summary"]
            ):
                streamed_text += delta
                partial_history = history + [
                    {"role": "assistant", "content": header + html.escape(streamed_text)}
                ]
                yield (
                    partial_history, "", *result_sections,
                    new_condition, result, session_id,
                    access_token_info, auth_state, *sidebar_update,
                )
        except Exception:
            # 설명 문장 생성 실패는 계획 자체의 실패가 아니므로, 고정 문구로 대체하고
            # 계속 진행한다(결과 패널은 이미 정상적으로 채워져 있음).
            used_fallback_reason = True
            streamed_text = (
                "위 조건으로 일정, 동선, 비용을 최적화했습니다. "
                "가운데 <b>결과 패널</b>에서 상세 내용을 확인해 주세요!"
            )

        reply = header + (
            streamed_text if used_fallback_reason else html.escape(streamed_text)
        )
        final_history = history + [{"role": "assistant", "content": reply}]

        if is_logged_in and session_id is not None:
            try:
                chat_store.append_message(
                    session_id, access_token_info["user_id"], "assistant", reply
                )
                chat_store.update_session_condition_summary(
                    session_id, access_token_info["user_id"], new_condition
                )
                # 결과 패널(일정/동선/비용)도 통째로 저장해둔다 — "최근 대화"에서 이
                # 세션을 다시 열었을 때 대화 내용뿐 아니라 그때 만든 일정도 같이 복원됨.
                chat_store.update_session_result(
                    session_id, access_token_info["user_id"], result
                )
                if is_first_message_in_session:
                    # 첫 메시지 그대로 자르는 대신(또는 "새 대화" 버튼으로 미리 만들어져
                    # 제목이 아예 없는 세션이든) 도시·기간으로 요약된 제목을 붙인다 —
                    # "최근 대화" 목록에서 어떤 여행인지 한눈에 알 수 있게.
                    chat_store.update_session_title(
                        session_id,
                        access_token_info["user_id"],
                        f"{city} {duration} 여행",
                    )
                    # 사이드바에 이미 임시 제목(또는 "새 대화")으로 보이던 항목을
                    # 최종 제목으로 다시 갱신한다.
                    sessions = chat_store.list_recent_sessions(access_token_info["user_id"])
                    sidebar_update = (
                        gr.update(choices=_session_choices(sessions), visible=True),
                        sessions,
                        gr.update(visible=False),
                    )
            except Exception:
                pass

        yield (
            final_history, "", *result_sections,
            new_condition, result, session_id,
            access_token_info, auth_state, *sidebar_update,
        )

    except ValueError as error:
        error_reply = f"여행 조건을 확인해주세요.\n\n- 원인: `{error}`"
        final_history = history + [{"role": "assistant", "content": error_reply}]
        yield (
            final_history, "", *NO_RESULT_UPDATE,
            previous_condition, previous_result, session_id,
            access_token_info, auth_state, *sidebar_update,
        )

    except Exception as error:
        error_reply = (
            "여행 계획을 생성하는 중 오류가 발생했습니다.\n\n"
            f"- 오류 종류: `{type(error).__name__}`\n"
            f"- 오류 내용: `{error}`"
        )
        final_history = history + [{"role": "assistant", "content": error_reply}]
        yield (
            final_history, "", *NO_RESULT_UPDATE,
            previous_condition, previous_result, session_id,
            access_token_info, auth_state, *sidebar_update,
        )


# ---------------------------------------------------------
# 대화 초기화 (새로운 대화)
# ---------------------------------------------------------
def clear_chat(access_token_info):
    is_logged_in = bool(access_token_info and access_token_info.get("access_token"))
    new_session_id = None
    sidebar_update = (gr.update(), gr.update(), gr.update())

    if is_logged_in:
        try:
            session_row = chat_store.create_session(access_token_info["user_id"])
            new_session_id = session_row["id"]
            # 여기서 만든 세션은 아직 제목/메시지가 없어 "새 대화"로만 보이지만(첫
            # 메시지를 보내면 chat()에서 도시·기간 제목으로 갱신됨), 최소한 사이드바
            # 목록에는 클릭 즉시 나타나야 한다.
            sessions = chat_store.list_recent_sessions(access_token_info["user_id"])
            # 방금 만든 새 세션을 목록에서 바로 선택된 상태로 보여준다 — 안 그러면
            # gr.update()가 value를 안 건드려서 이전에 선택돼 있던 다른 대화가 계속
            # 선택된 것처럼 보인다. session_radio.change가 다시 발화돼 load_session이
            # 한 번 더 불려도, 방금 만든 빈 세션 기준이라 이 함수가 이미 채운 값과
            # 동일해서(웰컴 메시지·빈 결과) 화면상 변화는 없다.
            sidebar_update = (
                gr.update(choices=_session_choices(sessions), value=new_session_id, visible=True),
                sessions,
                gr.update(visible=False),
            )
        except Exception:
            new_session_id = None

    return (
        [{"role": "assistant", "content": WELCOME_MESSAGE}],
        "",
        *RESET_RESULT_TUPLE,
        None,
        None,
        new_session_id,
        *sidebar_update,
    )


# ---------------------------------------------------------
# 언어 전환 — 설정 팝업의 "언어" 라디오로 UI 라벨을 교체한다.
# (Gradio는 gr.Tab 라벨을 런타임에 못 바꾸므로 탭 이름은 그대로 둔다.)
# ---------------------------------------------------------
def set_language(lang):
    t = I18N.get(lang, I18N["ko"])
    return (
        gr.update(value=t["new_chat"]),                       # clear_button
        gr.update(value=f"### {t['recent']}"),                # recent_title
        gr.update(placeholder=t["search_ph"]),                # search_box
        gr.update(value=f"### {t['req']}"),                   # req_title
        gr.update(label=t["transport"]),                      # transport_mode
        gr.update(label=t["people"]),                         # people_count
        gr.update(label=t["msg_label"], placeholder=t["msg_ph"]),  # message_input
        gr.update(value=t["send"]),                           # send_button
        gr.update(value=t["logout"]),                         # logout_button
        lang,                                                 # language_state
    )


# ---------------------------------------------------------
# 사이드바 접기/펼치기 — 접으면 좌측 컬럼을 숨기고 결과 패널이 넓어진다.
# ---------------------------------------------------------
def toggle_sidebar(is_open):
    new_open = not is_open
    return (
        gr.update(visible=new_open),                 # sidebar_body
        gr.update(value="←" if new_open else "→"),   # collapse_btn
        new_open,
    )


# ---------------------------------------------------------
# "CHAT A.I+" 스타일 CSS — 3단(사이드바 · 결과패널 · 요청사항) 다크 레이아웃
# ---------------------------------------------------------
CUSTOM_CSS = """
:root {
    /* 라이트 팔레트(기본값) — .dark 클래스가 없을 때(라이트 모드 선택 시) 적용된다 */
    --tr-outer-bg: #C9D6F2;
    --tr-app-bg: #FFFFFF;
    --tr-card-bg: #FFFFFF;
    --tr-primary: #6C63FF;
    --tr-primary-hover: #5A52E0;
    --tr-text: #1A1A1A;
    --tr-text-muted: #6B6D78;
    --tr-border: #EDEDF2;
    --tr-selected-bg: #EEF0FC;
    --tr-pill-bg: #F3F3F8;
    --tr-table-bg: #FAFAFC;
    --tr-table-header-bg: #F1F1FA;

    --color-accent: var(--tr-primary);
    --checkbox-background-color-selected: var(--tr-primary);
    --slider-color: var(--tr-primary);
    --button-primary-background-fill: var(--tr-primary);
    --button-primary-background-fill-hover: var(--tr-primary-hover);
}

.dark {
    /* 다크 팔레트 — Gradio가 dark 테마일 때 .gradio-container(또는 조상)에 붙이는 클래스 */
    --tr-outer-bg: #0f111b;
    --tr-app-bg: #161826;
    --tr-card-bg: #232532;
    --tr-primary: #9184d9;
    --tr-primary-hover: #a79ce6;
    --tr-text: #e9e9ed;
    --tr-text-muted: #9397ab;
    --tr-border: rgba(233,233,237,0.14);
    --tr-selected-bg: #2b2741;
    --tr-pill-bg: #1c1e2b;
    --tr-table-bg: #1c1e2b;
    --tr-table-header-bg: #262838;
}

.gradio-container { color-scheme: light; }
.dark.gradio-container, .dark .gradio-container { color-scheme: dark; }

:root, .dark, .gradio-container {
    --background-fill-primary: var(--tr-app-bg) !important;
    --background-fill-secondary: var(--tr-app-bg) !important;
    --body-background-fill: var(--tr-outer-bg) !important;
    --block-background-fill: var(--tr-card-bg) !important;
    --input-background-fill: var(--tr-pill-bg) !important;
    --body-text-color: var(--tr-text) !important;
    --border-color-primary: var(--tr-border) !important;
    --slider-color: var(--tr-primary) !important;
    --color-accent: var(--tr-primary) !important;
    --neutral-950: var(--tr-app-bg) !important;
}

body { background: var(--tr-outer-bg) !important; }

.gradio-container {
    max-width: 1720px !important;
    width: 97vw !important;
    margin: 28px auto !important;
    background: var(--tr-app-bg) !important;
    border-radius: 24px !important;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
    font-family: "Inter", "Pretendard", -apple-system, sans-serif;
    padding: 14px 24px 8px !important;
}

/* ── 상단 헤더: 로고 + 접기 화살표 ── */
#top-header { align-items: center !important; gap: 14px !important; margin-bottom: 8px; }
#logo-box { max-width: 190px !important; }
#logo-box img { height: 40px !important; width: auto !important; object-fit: contain; }
#logo-box .image-frame, #logo-box .image-container { border: none !important; background: transparent !important; box-shadow: none !important; padding: 0 !important; }
#logo-box button, #logo-box .icon-buttons { display: none !important; }

#collapse-btn {
    max-width: 44px !important; min-width: 44px !important;
    height: 40px; border-radius: 10px !important;
    background: var(--tr-card-bg) !important; border: 1px solid var(--tr-border) !important;
    color: var(--tr-text) !important; font-size: 18px; font-weight: 700;
}
#collapse-btn:hover { border-color: var(--tr-primary) !important; color: var(--tr-primary) !important; }

/* ── 사이드바 ── */
.sidebar {
    background: var(--tr-card-bg) !important;
    border: 1px solid var(--tr-border) !important;
    border-radius: 16px !important;
    padding: 18px !important;
    gap: 14px !important;
}

/* 프로필 (깔끔한 한 줄) */
.tr-profile { display: flex; align-items: center; gap: 11px; padding: 2px; }
.tr-avatar {
    width: 38px; height: 38px; flex: none; border-radius: 50%;
    background: var(--tr-primary); color: #fff;
    display: flex; align-items: center; justify-content: center;
    font-size: 15px; font-weight: 700;
}
.tr-profile-meta { min-width: 0; }
.tr-profile-name { font-size: 14px; font-weight: 700; color: var(--tr-text); line-height: 1.2; }
.tr-profile-email { font-size: 11.5px; color: var(--tr-text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#welcome-text .prose { background: transparent !important; }

#logout-btn {
    background: transparent !important; color: #ef4444 !important;
    border: 1px solid var(--tr-border) !important; font-weight: 600;
    border-radius: 10px !important; min-height: 38px;
}
#logout-btn:hover { background: rgba(239,68,68,0.14) !important; }

/* 새로운 대화 (사이드바 최상단 강조 버튼) */
#new-chat-button {
    background: transparent !important; color: var(--tr-primary) !important;
    border: 1px solid var(--tr-primary) !important;
    border-radius: 12px !important; font-weight: 700;
    min-height: 46px; font-size: 14px;
}
#new-chat-button:hover { background: var(--tr-selected-bg) !important; }

#recent-title h3 { font-size: 13px !important; font-weight: 700 !important; color: var(--tr-text-muted) !important; margin: 6px 2px 4px !important; text-transform: uppercase; letter-spacing: 0.04em; }
#recent-title .prose { background: transparent !important; }

#req-title h3 { font-size: 13px !important; font-weight: 700 !important; color: var(--tr-text-muted) !important; margin: 4px 2px 4px !important; text-transform: uppercase; letter-spacing: 0.04em; }
#req-title .prose { background: transparent !important; }

#search-box input {
    border-radius: 12px !important; border: 1px solid var(--tr-border) !important;
    background: var(--tr-pill-bg) !important; padding: 10px 14px !important; font-size: 13px !important; color: var(--tr-text) !important;
}
#search-box input:focus { border-color: var(--tr-primary) !important; }

#session-radio .wrap { display: flex !important; flex-direction: column; gap: 2px; background: transparent !important; border: none !important; }
#session-radio label {
    border: none !important; background: transparent !important; border-radius: 12px !important;
    padding: 10px 12px !important; font-size: 14px; color: var(--tr-text) !important; justify-content: flex-start !important;
}
#session-radio label input { display: none !important; }
#session-radio label.selected { background: var(--tr-selected-bg) !important; color: var(--tr-primary) !important; font-weight: 700; }

#login-trigger-btn {
    background: var(--tr-card-bg) !important; border: 1px solid var(--tr-border) !important;
    color: var(--tr-text) !important; border-radius: 999px !important; min-height: 44px; font-weight: 600;
}
#login-trigger-btn:hover { background: var(--tr-selected-bg) !important; }

/* ── 결과 패널 (가운데) ── */
#result-panel {
    background: var(--tr-card-bg) !important;
    border: 1px solid var(--tr-border) !important;
    border-radius: 16px !important; padding: 16px 20px 20px !important;
}
#result-panel .tab-nav {
    border-bottom: 1px solid var(--tr-border) !important; margin-bottom: 16px !important;
    display: flex !important; gap: 4px !important; background: transparent !important;
}
#result-panel .tab-nav button {
    padding: 10px 16px !important; font-size: 14px !important; color: var(--tr-text-muted) !important;
    border: none !important; background: transparent !important; border-bottom: 2px solid transparent !important;
    border-radius: 0 !important; font-weight: normal !important; cursor: pointer;
}
#result-panel .tab-nav button:hover { color: var(--tr-primary) !important; }
#result-panel .tab-nav button.selected { color: var(--tr-primary) !important; border-bottom-color: var(--tr-primary) !important; font-weight: 700 !important; }
#result-panel table {
    background: var(--tr-table-bg); border: 1px solid var(--tr-border); border-radius: 16px;
    border-collapse: separate; border-spacing: 0; overflow: hidden; width: 100%; font-size: 14px; margin-bottom: 20px;
}
#result-panel th { background: var(--tr-table-header-bg) !important; color: var(--tr-text-muted) !important; padding: 10px 14px !important; text-align: left; border: none !important; font-weight: normal; }
#result-panel td { padding: 10px 14px !important; border: none !important; border-top: 1px solid var(--tr-border) !important; color: var(--tr-text) !important; }
#result-panel tr:first-child td { border-top: none !important; }
#result-panel h3 { color: var(--tr-primary) !important; font-size: 15px !important; margin: 20px 0 8px !important; font-weight: 700 !important; }

/* ── 챗봇 / 입력 (오른쪽) ── */
#chatbot {
    min-height: 360px; background: var(--tr-card-bg) !important;
    border: 1px solid var(--tr-border) !important; border-radius: 16px !important;
    padding: 18px !important; box-sizing: border-box;
}
#chatbot .message.user {
    background: var(--tr-selected-bg) !important; border: none !important;
    border-radius: 20px 20px 4px 20px !important; color: var(--tr-text) !important;
    padding: 14px 18px !important; font-size: 15px !important; line-height: 1.6 !important; max-width: 92% !important;
}
#chatbot .message.user p:last-child { margin-bottom: 0 !important; }
#chatbot .message.bot { background: transparent !important; border: none !important; padding: 12px 4px !important; color: var(--tr-text) !important; font-size: 14px !important; line-height: 1.7 !important; white-space: pre-wrap !important; }

/* 이동수단: 세그먼트 pill */
#transport-mode .wrap { display: flex !important; flex-wrap: wrap; gap: 8px; background: transparent !important; border: none !important; }
#transport-mode label {
    display: inline-flex !important; align-items: center !important; justify-content: center !important;
    border: 1px solid var(--tr-border) !important; background: var(--tr-pill-bg) !important;
    border-radius: 999px !important; padding: 8px 14px !important; font-size: 13px; color: var(--tr-text) !important; white-space: nowrap;
}
#transport-mode label input { display: none !important; }
#transport-mode label.selected { background: var(--tr-primary) !important; color: #fff !important; border-color: var(--tr-primary) !important; font-weight: 600; }

input[type="range"], input[type="checkbox"] { accent-color: var(--tr-primary) !important; }

#message-input textarea {
    border-radius: 24px !important; border: 1px solid var(--tr-border) !important;
    box-shadow: 0 8px 24px rgba(40, 50, 110, 0.08) !important; padding: 14px 18px !important;
    font-size: 14px !important; color: var(--tr-text) !important; white-space: pre-wrap !important;
}
#message-input textarea:focus { border-color: var(--tr-primary) !important; }

#send-button {
    height: 48px !important; min-height: 48px !important; max-height: 48px !important;
    font-weight: 700; font-size: 14px; background: var(--tr-primary) !important;
    color: #fff !important; border-radius: 999px !important; padding: 12px 24px !important;
    overflow: hidden !important; white-space: nowrap !important;
    display: flex !important; align-items: center !important; justify-content: center !important;
}
#send-button:hover { background: var(--tr-primary-hover) !important; }

/* ── 하단 푸터 ── */
#app-footer { text-align: center; color: var(--tr-text-muted); font-size: 12px; padding: 14px 0 6px; }
#app-footer .prose { background: transparent !important; }
#footer-settings-btn {
    background: transparent !important; border: none !important; color: var(--tr-text-muted) !important;
    font-size: 12px !important; font-weight: 600; box-shadow: none !important; padding: 0 6px !important; min-width: 0 !important;
}
#footer-settings-btn:hover { color: var(--tr-primary) !important; }
#footer-row { justify-content: center !important; align-items: center !important; gap: 6px !important; flex-wrap: nowrap !important; margin-top: 4px; }
#footer-row > * { flex: 0 0 auto !important; }
#app-footer { width: auto !important; margin: 0 !important; min-width: 0 !important; }
#app-footer p { margin: 0 !important; }

/* ── 로그인 / 설정 모달 ──
   숨김은 Python의 visible=False가 담당(Gradio가 기본으로 렌더링을 건너뛴다).
   .hide 클래스는 열려 있던 모달을 강제로 즉시 접어야 할 때만 쓰는 보조 장치다.
   내부 컨텐츠(로그인 폼/설정 라디오)가 접히지 않도록 display는 block 하나로 통일한다
   (flex + 접힌 자식 조합에서 로그인 폼이 통째로 안 보이는 문제가 있었음). */
#auth-overlay, #settings-overlay {
    position: fixed !important; inset: 0 !important; width: 100vw !important; height: 100vh !important;
    background: rgba(0,0,0,0.4) !important; z-index: 99998 !important; backdrop-filter: blur(4px);
    margin: 0 !important; padding: 0 !important;
}
#auth-modal, #settings-modal {
    position: fixed !important; top: 50% !important; left: 50% !important; transform: translate(-50%, -50%) !important;
    z-index: 99999 !important; width: 400px !important; max-width: 90vw !important;
    background: var(--tr-card-bg) !important; box-shadow: 0 20px 60px rgba(0,0,0,0.5), 0 0 0 1px var(--tr-border) !important;
    border-radius: 24px !important; padding: 30px !important; margin: 0 !important; box-sizing: border-box !important;
}
#auth-overlay.hide, #auth-modal.hide, #settings-overlay.hide, #settings-modal.hide {
    display: none !important; opacity: 0 !important; pointer-events: none !important;
}
#auth-modal h3, #settings-modal h3 { margin: 0 0 18px 0 !important; font-size: 20px !important; text-align: center !important; color: var(--tr-text) !important; }
#close-modal-btn, #close-settings-btn {
    position: absolute !important; top: 16px !important; right: 16px !important;
    width: 32px !important; height: 32px !important; min-width: 32px !important;
    border-radius: 50% !important; background: var(--tr-pill-bg) !important; border: none !important;
    color: var(--tr-text) !important; font-size: 16px !important; font-weight: bold !important; padding: 0 !important;
    display: flex !important; align-items: center !important; justify-content: center !important;
    z-index: 999999 !important; cursor: pointer !important;
}
#close-modal-btn:hover, #close-settings-btn:hover { background: var(--tr-selected-bg) !important; }
#login-btn { background: var(--tr-primary) !important; color: #fff !important; border: none !important; }
#login-btn:hover { background: var(--tr-primary-hover) !important; }
#signup-btn { background: var(--tr-pill-bg) !important; color: var(--tr-text) !important; border: 1px solid var(--tr-border) !important; }
#signup-btn:hover { background: var(--tr-selected-bg) !important; }
#auth-message { color: var(--tr-primary) !important; font-size: 14px !important; font-weight: 600 !important; text-align: center !important; margin-top: 12px !important; }

input[type="text"], input[type="password"] { background-color: var(--tr-pill-bg) !important; color: var(--tr-text) !important; border: 1px solid var(--tr-border) !important; }
span[data-testid="block-info"] { color: var(--tr-text) !important; opacity: 1 !important; }

#settings-modal .setting-label { font-size: 12px; font-weight: 700; color: var(--tr-text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin: 6px 2px; }
#theme-radio .wrap, #lang-radio .wrap { display: flex !important; gap: 8px; background: transparent !important; border: none !important; }
#theme-radio label, #lang-radio label {
    flex: 1; justify-content: center !important; border: 1px solid var(--tr-border) !important;
    background: var(--tr-pill-bg) !important; border-radius: 10px !important; padding: 10px !important; font-size: 13px;
}
#theme-radio label input, #lang-radio label input { display: none !important; }
#theme-radio label.selected, #lang-radio label.selected { background: var(--tr-primary) !important; color: #fff !important; border-color: var(--tr-primary) !important; font-weight: 700; }

/* Gradio 기본 하단 푸터 숨김 (중복 방지) */
footer { display: none !important; }

/* 세 박스 높이 맞춤 */
#result-panel { height: 100% !important; box-sizing: border-box; }
.sidebar { height: 100% !important; box-sizing: border-box; }
"""

HEAD_HTML = """
<link rel="stylesheet" as="style" crossorigin
  href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css" />
<link rel="stylesheet"
  href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" />
<script>
  // 다크 테마로 강제 — Gradio가 마운트 시점에 URL의 ?__theme 를 즉시 읽는다.
  (function () {
    var u = new URL(window.location.href);
    if (u.searchParams.get('__theme') !== 'dark' && !u.searchParams.get('__theme')) {
      u.searchParams.set('__theme', 'dark');
      window.location.replace(u.toString());
    }
  })();
</script>
"""


# ---------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------
with gr.Blocks(title="TripRoute AI 여행 플래너") as demo:

    # 로그인 지속용: 브라우저 localStorage에 refresh_token/user_id/email만 저장한다.
    # access_token은 절대 여기 저장하지 않는다(서버 State에만 둠) — 백엔드가 service_role
    # 키만 쓰고 RLS를 안 타므로 access_token은 "누가 로그인했는지 증명"하는 용도 그 이상이
    # 아니고, 굳이 브라우저에 남길 필요가 없다.
    auth_browser_state = gr.BrowserState(dict(GUEST_BROWSER_STATE))
    access_token_state = gr.State(None)
    previous_condition_state = gr.State(None)
    # 직전 턴의 전체 결과(daily_schedule/route_summary 포함) — 기간 연장 후속 요청에서
    # 기존 일정을 유지한 채 늘어난 날짜만 새로 채우는 데 쓴다(previous_condition_state와
    # 항상 같이 갱신됨).
    previous_result_state = gr.State(None)
    active_session_id_state = gr.State(None)
    recent_sessions_state = gr.State([])
    sidebar_open_state = gr.State(True)
    language_state = gr.State("ko")
    # 마지막으로 고른 테마(dark/light)를 localStorage에 저장해 새로고침 후에도
    # 설정 라디오가 실제 적용된 테마를 그대로 보여주게 한다.
    theme_browser_state = gr.BrowserState("dark")

    # ── 상단 헤더: 로고 + 접기 화살표 ──
    with gr.Row(elem_id="top-header"):
        if LOGO_PATH.exists():
            gr.Image(
                value=str(LOGO_PATH),
                show_label=False,
                interactive=False,
                show_download_button=False,
                show_fullscreen_button=False,
                container=False,
                elem_id="logo-box",
            )
        else:
            gr.Markdown("## 🗺️ TripRoute", elem_id="logo-box")
        collapse_btn = gr.Button("←", elem_id="collapse-btn")

    # ── 로그인 / 설정 모달 ── 기본은 visible=False로 숨겨두고(Gradio 자체 렌더 스킵),
    # 열 때 Python이 visible=True로 바꾸는 동시에 JS로 위치/투명도용 클래스를 맞춘다.
    # gr.Group은 elem_id가 같은 div를 두 겹으로 렌더링해서(바깥 wrapper + 실제 컴포넌트),
    # position:fixed 같은 CSS가 안쪽 겹까지 겹쳐 적용되며 내용이 다른 위치로 빠져버리는
    # 문제가 있었다. gr.Column은 elem_id를 한 겹에만 렌더링해서 이 문제가 없다.
    with gr.Column(visible=False, elem_id="auth-overlay") as auth_overlay:
        pass

    with gr.Column(visible=False, elem_id="auth-modal") as auth_modal:
        close_modal_btn = gr.Button("✕", elem_id="close-modal-btn")
        with gr.Column(visible=True, elem_id="logged-out-group") as logged_out_group:
            gr.Markdown("### 로그인 / 회원가입")
            email_input = gr.Textbox(label="이메일")
            password_input = gr.Textbox(label="비밀번호", type="password")
            with gr.Row():
                login_button = gr.Button("로그인", variant="primary", elem_id="login-btn")
                signup_button = gr.Button("회원가입", variant="secondary", elem_id="signup-btn")
            auth_message = gr.Markdown("", elem_id="auth-message")

    with gr.Column(visible=False, elem_id="settings-overlay") as settings_overlay:
        pass

    with gr.Column(visible=False, elem_id="settings-modal") as settings_modal:
        close_settings_btn = gr.Button("✕", elem_id="close-settings-btn")
        gr.Markdown("### 설정")
        gr.Markdown("<div class='setting-label'>테마</div>")
        theme_radio = gr.Radio(
            choices=[("다크 모드", "dark"), ("라이트 모드", "light")],
            value="dark", show_label=False, elem_id="theme-radio",
        )
        gr.Markdown("<div class='setting-label'>언어 / Language</div>")
        lang_radio = gr.Radio(
            choices=[("한국어", "ko"), ("English", "en")],
            value="ko", show_label=False, elem_id="lang-radio",
        )

    # ── 3단 본문 ──
    with gr.Row(equal_height=True):

        # 왼쪽: 사이드바
        with gr.Column(scale=1, min_width=250, elem_classes=["sidebar"], elem_id="sidebar-col") as sidebar_body:
            login_trigger_btn = gr.Button("👤 로그인 / 내 정보", elem_id="login-trigger-btn")

            with gr.Group(visible=False, elem_id="logged-in-group") as logged_in_group:
                welcome_text = gr.Markdown("", elem_id="welcome-text")
                logout_button = gr.Button("로그아웃", elem_id="logout-btn")

            clear_button = gr.Button(I18N["ko"]["new_chat"], elem_id="new-chat-button")

            recent_title = gr.Markdown(f"### {I18N['ko']['recent']}", elem_id="recent-title")
            search_box = gr.Textbox(
                show_label=False, placeholder=I18N["ko"]["search_ph"],
                elem_id="search-box", lines=1,
            )
            session_radio = gr.Radio(choices=[], label="", show_label=False, elem_id="session-radio")
            no_session_msg = gr.Markdown("최근 대화 내역이 없습니다.", elem_id="no-session-msg", visible=False)

        # 가운데: 결과 패널
        with gr.Column(scale=3, min_width=460):
            with gr.Column(elem_id="result-panel"):
                with gr.Tabs():
                    with gr.Tab("일정표"):
                        schedule_out = gr.Markdown(RESULT_PLACEHOLDER)
                    with gr.Tab("이동 동선"):
                        route_out = gr.Markdown(RESULT_PLACEHOLDER)
                    with gr.Tab("예상 비용"):
                        cost_out = gr.Markdown(RESULT_PLACEHOLDER)
                    with gr.Tab("조건 요약"):
                        condition_out = gr.Markdown(RESULT_PLACEHOLDER)

        # 오른쪽: 요청사항 (대화 + 설정 + 입력)
        with gr.Column(scale=2, min_width=360):
            req_title = gr.Markdown(f"### {I18N['ko']['req']}", elem_id="req-title")
            chatbot = gr.Chatbot(
                show_label=False, height=360, elem_id="chatbot",
                value=[{"role": "assistant", "content": WELCOME_MESSAGE}],
                buttons=["copy"], feedback_options=("Like", "Dislike"),
            )

            transport_mode = gr.Radio(
                choices=["대중교통", "택시", "자차", "렌터카"],
                value="대중교통", label="이동수단", elem_id="transport-mode",
            )
            people_count = gr.Slider(minimum=1, maximum=10, step=1, value=2, label="여행 인원")

            message_input = gr.Textbox(
                label="여행 요청",
                placeholder=I18N["ko"]["msg_ph"],
                lines=1, max_lines=5, elem_id="message-input",
            )
            send_button = gr.Button("여행 계획 생성", variant="primary", elem_id="send-button")

    # ── 하단 푸터 ──
    with gr.Row(elem_id="footer-row"):
        gr.Markdown(
            "TripRoute AI 여행 플래너 · Solar API 기반 (일부 항목은 Mock 데이터/추정치) 🧡",
            elem_id="app-footer",
        )
        footer_settings_btn = gr.Button("설정 ⚙️", elem_id="footer-settings-btn")

    # -----------------------------------------------------
    # 이벤트 연결
    # -----------------------------------------------------
    result_tab_outputs = [
        schedule_out,
        route_out,
        cost_out,
        condition_out,
    ]

    chat_outputs = [
        chatbot,
        message_input,
        *result_tab_outputs,
        previous_condition_state,
        previous_result_state,
        active_session_id_state,
        access_token_state,
        auth_browser_state,
        session_radio,
        recent_sessions_state,
        no_session_msg,
    ]

    chat_inputs = [
        message_input,
        chatbot,
        transport_mode,
        people_count,
        access_token_state,
        previous_condition_state,
        previous_result_state,
        active_session_id_state,
        auth_browser_state,
    ]

    send_button.click(fn=chat, inputs=chat_inputs, outputs=chat_outputs, show_progress="minimal")
    message_input.submit(fn=chat, inputs=chat_inputs, outputs=chat_outputs, show_progress="minimal")

    clear_chat_outputs = [
        chatbot,
        message_input,
        *result_tab_outputs,
        previous_condition_state,
        previous_result_state,
        active_session_id_state,
        session_radio,
        recent_sessions_state,
        no_session_msg,
    ]

    clear_button.click(fn=clear_chat, inputs=[access_token_state], outputs=clear_chat_outputs)

    # 최근 대화 검색
    search_box.change(
        fn=search_sessions,
        inputs=[search_box, recent_sessions_state],
        outputs=[session_radio],
    )

    # 사이드바 접기/펼치기
    collapse_btn.click(
        fn=toggle_sidebar,
        inputs=[sidebar_open_state],
        outputs=[sidebar_body, collapse_btn, sidebar_open_state],
    )

    auth_outputs = [
        logged_out_group,
        logged_in_group,
        welcome_text,
        session_radio,
        no_session_msg,
        access_token_state,
        auth_browser_state,
        recent_sessions_state,
        login_trigger_btn,
        auth_message,
        auth_overlay,
        auth_modal,
    ]

    def open_auth_modal():
        return gr.update(visible=True), gr.update(visible=True)

    def close_auth_modal():
        return gr.update(visible=False), gr.update(visible=False)

    def open_settings_modal():
        return gr.update(visible=True), gr.update(visible=True)

    def close_settings_modal():
        return gr.update(visible=False), gr.update(visible=False)

    # Python의 visible 토글만으로는 모달이 안 닫히는 경우가 있어(내부적으로 크기만
    # 접으려 하고 position:fixed 같은 !important 크기 지정이 그 축소를 덮어씀), JS로
    # "hide" 클래스를 같이 토글해 이중으로 확실히 여닫는다.
    OPEN_MODAL_JS = """
    () => {
        document.getElementById('auth-overlay')?.classList.remove('hide');
        document.getElementById('auth-modal')?.classList.remove('hide');
    }
    """
    CLOSE_MODAL_JS = """
    () => {
        document.getElementById('auth-overlay')?.classList.add('hide');
        document.getElementById('auth-modal')?.classList.add('hide');
    }
    """
    OPEN_SETTINGS_JS = """
    () => {
        document.getElementById('settings-overlay')?.classList.remove('hide');
        document.getElementById('settings-modal')?.classList.remove('hide');
    }
    """
    CLOSE_SETTINGS_JS = """
    () => {
        document.getElementById('settings-overlay')?.classList.add('hide');
        document.getElementById('settings-modal')?.classList.add('hide');
    }
    """
    # 테마: ?__theme= 쿼리로 다크/라이트를 강제하고 새로고침(Gradio가 마운트 시점에 즉시 읽는다)
    # theme_radio 값은 페이지 로드 시 sync_theme_radio(demo.load)가 저장된 테마로도
    # 다시 세팅하는데, Gradio는 프로그램적으로 값을 바꿔도 change 이벤트가 다시 발화된다.
    # 그래서 가드 없이 무조건 리로드하면 로드→동기화→change→리로드→로드→... 로 무한
    # 새로고침 루프에 빠진다. 이미 그 테마로 떠 있는 페이지면 아무것도 하지 않는다.
    APPLY_THEME_JS = """
    (theme) => {
        const url = new URL(window.location.href);
        const current = url.searchParams.get('__theme') || 'dark';
        if (current === theme) return;
        url.searchParams.set('__theme', theme);
        window.location.href = url.toString();
    }
    """

    login_trigger_btn.click(
        fn=open_auth_modal, inputs=[], outputs=[auth_overlay, auth_modal]
    ).then(fn=None, js=OPEN_MODAL_JS)
    close_modal_btn.click(
        fn=close_auth_modal, inputs=[], outputs=[auth_overlay, auth_modal]
    ).then(fn=None, js=CLOSE_MODAL_JS)

    footer_settings_btn.click(
        fn=open_settings_modal, inputs=[], outputs=[settings_overlay, settings_modal]
    ).then(fn=None, js=OPEN_SETTINGS_JS)
    close_settings_btn.click(
        fn=close_settings_modal, inputs=[], outputs=[settings_overlay, settings_modal]
    ).then(fn=None, js=CLOSE_SETTINGS_JS)

    theme_radio.change(
        fn=save_theme, inputs=[theme_radio], outputs=[theme_browser_state]
    ).then(fn=None, inputs=[theme_radio], js=APPLY_THEME_JS)

    lang_radio.change(
        fn=set_language,
        inputs=[lang_radio],
        outputs=[
            clear_button, recent_title, search_box, req_title,
            transport_mode, people_count, message_input, send_button, logout_button,
            language_state,
        ],
    )

    demo.load(fn=restore_login, inputs=[auth_browser_state], outputs=auth_outputs)
    demo.load(fn=sync_theme_radio, inputs=[theme_browser_state], outputs=[theme_radio])

    # 로그인/회원가입 성공 시 auth_overlay/auth_modal을 직접 visible=False로 닫는다
    # (auth_outputs에 이미 포함됨) — 실패 시엔 gr.update()라 열린 채로 유지되고
    # auth_message에 에러가 표시된다. 화면에서 요소 높이를 측정해 성공 여부를 추정하던
    # 예전 JS 방식은 타이밍에 따라 판단이 씹혀서 모달이 안 닫히고 남는 문제가 있었다.
    login_button.click(fn=do_login, inputs=[email_input, password_input], outputs=auth_outputs)
    signup_button.click(fn=do_signup, inputs=[email_input, password_input], outputs=auth_outputs)

    logout_button.click(
        fn=do_logout,
        inputs=[access_token_state, auth_browser_state],
        outputs=[
            *auth_outputs,
            chatbot,
            message_input,
            previous_condition_state,
            previous_result_state,
            active_session_id_state,
        ],
    )

    session_radio.change(
        fn=load_session,
        inputs=[session_radio, auth_browser_state],
        outputs=[
            chatbot,
            message_input,
            previous_condition_state,
            previous_result_state,
            active_session_id_state,
            *result_tab_outputs,
        ],
    )


# ---------------------------------------------------------
# 실행
# ---------------------------------------------------------
if __name__ == "__main__":
    demo.queue()

    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        show_error=True,
        theme=gr.themes.Default(),
        css=CUSTOM_CSS,
        head=HEAD_HTML,
        allowed_paths=[str(LOGO_PATH.parent)],
    )
