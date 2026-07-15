"""MathMate 학생용 채팅 화면 (Streamlit).

FastAPI 백엔드(/api/chat)의 SSE 스트림을 받아 튜터 답변을 타이핑되듯 보여준다.
초등학생(4~6학년) 사용자를 위해 화면엔 튜터의 말만 보여주고,
intent/diagnosis 같은 내부 처리 과정은 절대 노출하지 않는다.

- 학생 말풍선은 왼쪽(하늘색), 튜터 말풍선은 오른쪽(따뜻한 노란색)으로 배치.
- 처음 접속하면 이름+학년으로 간단한 프로필(비밀번호 없음)을 만들고,
  사이드바에서 "학습"/"피드백" 화면을 오갈 수 있다.
"""
import html as html_lib
import os

import httpx
import streamlit as st

BACKEND_URL = os.getenv("MATHMATE_BACKEND_URL", "http://127.0.0.1:8000")
TUTOR_AVATAR = "🧮"
STUDENT_AVATAR = "🧒"
CONGRATS_MARKERS = ["정확해요", "잘했어요"]
STUDENT_BUBBLE_COLOR = "#E3F2FD"
TUTOR_BUBBLE_COLOR = "#FFF3C4"
MASTERY_COLOR = {"취약": "#EF6B6B", "보통": "#F0A93E", "잘함": "#3FB27F"}

st.set_page_config(page_title="MathMate", page_icon="🧮", layout="centered")

st.markdown(
    """
    <style>
    html, body, [class*="css"] {
        font-size: 17px !important;
        line-height: 1.7 !important;
    }
    .stApp {
        background: linear-gradient(180deg, #FFF9EC 0%, #EAF6FF 100%);
    }
    h1 {
        color: #FF8FAB;
    }
    .stButton>button {
        border-radius: 999px;
        font-size: 17px;
        padding: 0.5em 1.2em;
        background-color: #FFD6E8;
        border: none;
    }
    .problem-card {
        background-color: #FFFFFF;
        border: 1px solid #D8ECFF;
        border-radius: 18px;
        padding: 16px 20px;
        font-size: 18px;
        margin-bottom: 16px;
    }
    .mastery-card {
        background-color: #FFFFFF;
        border: 1px solid #EEE;
        border-radius: 18px;
        padding: 16px 20px;
        margin-bottom: 14px;
    }
    .mastery-bar-track {
        background-color: #F0F0F0;
        border-radius: 999px;
        height: 10px;
        margin: 10px 0 8px 0;
    }
    .mastery-bar-fill {
        border-radius: 999px;
        height: 10px;
    }
    .mastery-tag {
        border-radius: 999px;
        padding: 4px 14px;
        font-size: 14px;
        font-weight: 700;
    }
    .recommend-banner {
        background-color: #DCEBFF;
        border-radius: 18px;
        padding: 18px 22px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def create_or_get_profile(login_id: str, name: str, grade: int, semester: int, password: str):
    """성공하면 프로필 dict, 아이디는 있는데 비번이 다르면 'wrong_password',
    아이디·비번은 맞는데 이름이 다르면 'name_mismatch', 연결 실패면 None."""
    try:
        res = httpx.post(f"{BACKEND_URL}/api/profile",
                          json={"login_id": login_id, "name": name, "grade": grade,
                                "semester": semester, "password": password},
                          timeout=5)
        if res.status_code == 401:
            return "wrong_password"
        if res.status_code == 409:
            return "name_mismatch"
        res.raise_for_status()
        return res.json()
    except httpx.HTTPError:
        return None


def fetch_semesters(grade: int) -> list[int]:
    try:
        res = httpx.get(f"{BACKEND_URL}/api/problems/semesters", params={"grade": grade}, timeout=5)
        res.raise_for_status()
        return res.json()["semesters"]
    except httpx.HTTPError:
        return []


def fetch_units(grade: int, semester: int) -> list[str]:
    try:
        res = httpx.get(f"{BACKEND_URL}/api/problems/units", params={"grade": grade, "semester": semester},
                         timeout=5)
        res.raise_for_status()
        return res.json()["units"]
    except httpx.HTTPError:
        return []


def fetch_problems(grade: int, semester: int, unit: str | None, difficulty: str | None) -> list[dict]:
    params = {"grade": grade, "semester": semester}
    if unit:
        params["unit"] = unit
    if difficulty:
        params["difficulty"] = difficulty
    try:
        res = httpx.get(f"{BACKEND_URL}/api/problems", params=params, timeout=5)
        res.raise_for_status()
        return res.json()["items"]
    except httpx.HTTPError:
        return []


def fetch_feedback(user_id: int, grade: int | None = None, semester: int | None = None) -> dict | None:
    params = {"user_id": user_id}
    if grade is not None:
        params["grade"] = grade
    if semester is not None:
        params["semester"] = semester
    try:
        res = httpx.get(f"{BACKEND_URL}/api/feedback", params=params, timeout=5)
        res.raise_for_status()
        return res.json()
    except httpx.HTTPError:
        return None


def parse_sse_lines(lines):
    """sse-starlette가 보낸 'data: <chunk>' 줄에서 원문 청크만 뽑아낸다.

    청크 자체가 공백일 수 있으므로 strip()을 쓰면 안 되고,
    'data:' 뒤에 붙는 구분용 공백 1개만 제거한다.
    """
    for line in lines:
        if not line.startswith("data:"):
            continue
        content = line[len("data:"):]
        if content.startswith(" "):
            content = content[1:]
        yield content


def render_bubble(role: str, text: str, placeholder=None):
    """학생=왼쪽/하늘색, 튜터=오른쪽/노란색 말풍선을 그린다."""
    safe_text = html_lib.escape(text).replace("\n", "<br>")
    if role == "user":
        block = f"""
        <div style="display:flex; justify-content:flex-start; align-items:flex-end; margin:14px 0;">
          <div style="font-size:26px; margin-right:8px;">{STUDENT_AVATAR}</div>
          <div style="background:{STUDENT_BUBBLE_COLOR}; border-radius:20px; padding:12px 16px;
                      max-width:75%; font-size:17px; line-height:1.7; color:#2B2B2B;">
            {safe_text}
          </div>
        </div>
        """
    else:
        block = f"""
        <div style="display:flex; justify-content:flex-end; align-items:flex-end; margin:14px 0;">
          <div style="background:{TUTOR_BUBBLE_COLOR}; border-radius:20px; padding:12px 16px;
                      max-width:75%; font-size:17px; line-height:1.7; color:#2B2B2B; text-align:left;">
            {safe_text}
          </div>
          <div style="font-size:26px; margin-left:8px;">{TUTOR_AVATAR}</div>
        </div>
        """
    (placeholder if placeholder is not None else st).markdown(block, unsafe_allow_html=True)


def render_thinking_bubble(placeholder):
    """응답 첫 글자가 오기 전, 튜터가 생각 중이라는 걸 보여주는 임시 말풍선."""
    block = f"""
    <div style="display:flex; justify-content:flex-end; align-items:flex-end; margin:14px 0;">
      <div style="background:{TUTOR_BUBBLE_COLOR}; border-radius:20px; padding:12px 16px;
                  max-width:75%; font-size:17px; line-height:1.7; color:#8A7A4A;">
        🧮 생각하고 있어요... 💭
      </div>
      <div style="font-size:26px; margin-left:8px;">{TUTOR_AVATAR}</div>
    </div>
    """
    placeholder.markdown(block, unsafe_allow_html=True)


def stream_tutor_reply(user_id: int, problem_id: str, message: str, placeholder) -> str:
    payload = {"student_id": str(user_id), "problem_id": problem_id, "message": message}
    full_text = ""
    with httpx.stream("POST", f"{BACKEND_URL}/api/chat", json=payload, timeout=None) as res:
        for line in res.iter_lines():
            for chunk in parse_sse_lines([line]):
                full_text += chunk
                render_bubble("assistant", full_text, placeholder)
    return full_text


def mastery_bar_width(avg_hints_used: float) -> int:
    """힌트를 적게 쓸수록 막대가 길어지는 0~100 점수(시각화용)."""
    score = 100 / (1 + avg_hints_used)
    return max(5, min(100, round(score)))


# ---------- 프로필(로그인 대체) ----------
# 새로고침해도 로그인 화면으로 안 돌아가도록, 로그인 성공 시 프로필을 URL 쿼리 파라미터에도
# 저장해둔다. Streamlit은 브라우저를 새로고침하면 session_state가 초기화되지만
# 쿼리 파라미터는 URL에 남아있어서, 시작할 때 여기서 다시 읽어와 세션을 복원한다.

def _restore_user_from_query_params():
    q = st.query_params
    uid = q.get("uid")
    if not uid:
        return None
    try:
        return {
            "user_id": int(uid),
            "login_id": q.get("login_id", ""),
            "name": q.get("name", ""),
            "grade": int(q.get("grade", 4)),
            "semester": int(q.get("semester", 1)),
        }
    except (TypeError, ValueError):
        return None


def _login(profile: dict):
    st.session_state.user = profile
    st.query_params.update({
        "uid": str(profile["user_id"]), "login_id": profile["login_id"],
        "name": profile["name"], "grade": str(profile["grade"]), "semester": str(profile["semester"]),
    })


def _logout():
    del st.session_state.user
    st.query_params.clear()


if "user" not in st.session_state:
    restored = _restore_user_from_query_params()
    if restored:
        st.session_state.user = restored

if "user" not in st.session_state:
    st.title("🧮 MathMate")
    st.caption("먼저 아이디, 이름, 학년, 비밀번호를 알려줄래? 😊")
    st.caption("아이디는 다른 친구랑 겹치면 안 돼! 비밀번호는 나중에 다시 들어올 때 '나'인지 확인하는 용도야.")

    with st.form("profile_form"):
        login_id = st.text_input("아이디를 정해줄래? (영문/숫자)")
        name = st.text_input("이름이 뭐야?")
        grade = st.selectbox("몇 학년이야?", [4, 5, 6])
        semester = st.selectbox("몇 학기야?", [1, 2])
        password = st.text_input("비밀번호(암호)를 정해줄래?", type="password")
        submitted = st.form_submit_button("시작하기 ✏️")
    if submitted:
        if not login_id.strip():
            st.warning("아이디를 입력해줄래?")
        elif not name.strip():
            st.warning("이름을 입력해줄래?")
        elif not password:
            st.warning("비밀번호도 정해줄래?")
        else:
            profile = create_or_get_profile(login_id.strip(), name.strip(), grade, semester, password)
            if profile is None:
                st.error("앗, 서버랑 연결이 안 돼요. 선생님을 불러주세요!")
            elif profile == "wrong_password":
                st.error("어? 그 아이디는 이미 있는데 비밀번호가 달라요. 다시 확인해줄래?")
            elif profile == "name_mismatch":
                st.error("어? 그 아이디는 이미 있는데 이름이 달라요. 아이디를 다시 확인해줄래?")
            else:
                _login(profile)
                st.rerun()
    st.stop()

user = st.session_state.user

# ---------- 사이드바 네비게이션 ----------

st.sidebar.markdown(f"### 🧮 MathMate\n**{user['name']}** ({user['grade']}학년 {user['semester']}학기)")
page = st.sidebar.radio("메뉴", ["💬 학습", "📊 피드백"], label_visibility="collapsed")
if st.sidebar.button("🚪 로그아웃"):
    _logout()
    st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = []
if "selected_grade" not in st.session_state:
    st.session_state.selected_grade = user["grade"]
if "selected_semester" not in st.session_state:
    st.session_state.selected_semester = user["semester"]


# ---------- 학습 화면 ----------

def _search_problems(grade, semester, unit, difficulty):
    """'문제 조회' 버튼 콜백: 조건에 맞는 문제를 찾아 첫 문제를 고르고 채팅을 초기화한다."""
    problems = fetch_problems(grade, semester, unit, difficulty)
    st.session_state.searched_problems = problems
    st.session_state.searched_key = (grade, semester, unit, difficulty)
    st.session_state.messages = []
    if problems:
        st.session_state.problem_id = problems[0]["id"]
        st.session_state._last_problem_id = problems[0]["id"]


def render_study_page():
    st.title("🧮 MathMate")
    st.caption("선생님이랑 같이 수학 문제를 풀어볼까요? 😊")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        grade = st.selectbox("학년", [4, 5, 6], key="selected_grade")

    semesters = fetch_semesters(grade) or [1, 2]
    if st.session_state.selected_semester not in semesters:
        st.session_state.selected_semester = semesters[0]
    with col2:
        semester = st.selectbox("학기", semesters, key="selected_semester")

    units = fetch_units(grade, semester)
    if not units:
        st.info("이 학년·학기엔 아직 문제가 없어요. 다른 학년이나 학기를 골라볼까요?")
        return
    with col3:
        default_unit = st.session_state.pop("preselect_unit", None)
        if st.session_state.get("selected_unit") not in units:
            st.session_state.selected_unit = default_unit if default_unit in units else units[0]
        unit = st.selectbox("단원", units, key="selected_unit")
    with col4:
        difficulty = st.selectbox("난이도", ["쉬움", "중간", "어려움"], key="selected_difficulty")

    st.button("🔍 문제 조회", type="primary",
              on_click=_search_problems, args=(grade, semester, unit, difficulty))

    if "searched_key" not in st.session_state:
        st.info("👆 학년·학기·단원·난이도를 고르고 '문제 조회'를 눌러줘!")
        return

    problems = st.session_state.searched_problems
    if not problems:
        st.info("이 조건에 맞는 문제가 아직 없어요. 다른 난이도나 단원을 골라볼까요?")
        return

    labels = {p["id"]: f'{p["problem"][:24]}...' if len(p["problem"]) > 24 else p["problem"] for p in problems}

    problem_id = st.selectbox(
        "어떤 문제를 풀어볼까요?",
        options=list(labels.keys()),
        format_func=lambda pid: labels[pid],
        key="problem_id",
    )

    # 문제가 바뀐 이유(직접 선택/새 조회/새 문제 보기 버튼)에 상관없이,
    # 이전에 보여준 문제와 달라졌으면 채팅 기록을 초기화한다.
    if st.session_state.get("_last_problem_id") != problem_id:
        st.session_state.messages = []
        st.session_state._last_problem_id = problem_id

    current_problem = next(p for p in problems if p["id"] == problem_id)
    st.markdown(f'<div class="problem-card">📝 {current_problem["problem"]}</div>', unsafe_allow_html=True)

    def _go_to_next_problem(ids):
        idx = ids.index(st.session_state.problem_id)
        st.session_state.problem_id = ids[(idx + 1) % len(ids)]

    st.button("🔄 새 문제 보기", on_click=_go_to_next_problem, args=(list(labels.keys()),))

    for msg in st.session_state.messages:
        render_bubble(msg["role"], msg["content"])

    user_message = st.chat_input("여기에 답을 써 볼까? ✏️")

    if user_message:
        st.session_state.messages.append({"role": "user", "content": user_message})
        render_bubble("user", user_message)

        placeholder = st.empty()
        render_thinking_bubble(placeholder)
        reply = stream_tutor_reply(user["user_id"], problem_id, user_message, placeholder)
        st.session_state.messages.append({"role": "assistant", "content": reply})

        if any(marker in reply for marker in CONGRATS_MARKERS):
            st.balloons()
            st.success("🎉 정답이에요! 참 잘했어요! 🎉")


# ---------- 피드백 화면 ----------

def render_feedback_page():
    st.title("📊 단원별 학습 리포트")
    st.caption("힌트를 적게 쓰고 스스로 풀수록 숙련도가 높아요")

    col1, col2 = st.columns(2)
    with col1:
        grade_options = ["전체"] + [4, 5, 6]
        grade_choice = st.selectbox("학년", grade_options, key="feedback_grade")
    with col2:
        semester_options = ["전체", 1, 2]
        semester_choice = st.selectbox("학기", semester_options, key="feedback_semester")

    grade = None if grade_choice == "전체" else grade_choice
    semester = None if semester_choice == "전체" else semester_choice

    feedback = fetch_feedback(user["user_id"], grade, semester)
    if feedback is None:
        st.error("앗, 서버랑 연결이 안 돼요. 선생님을 불러주세요!")
        st.stop()

    summary = feedback["summary"]
    if summary["total_attempts"] == 0:
        st.info("아직 푼 문제가 없어요. 학습 화면에서 문제를 풀어보면 여기에 리포트가 쌓여요!")
        return

    st.markdown(f'<div class="recommend-banner" style="margin-bottom:18px; display:block;">'
                f'<div style="font-size:17px; color:#1B4E8F; font-weight:600; margin-bottom:14px;">'
                f'{html_lib.escape(summary["message"])}</div>'
                f'<div style="display:flex; gap:10px; flex-wrap:wrap;">'
                + "".join(
                    f'<div style="background:#FFFFFF; border-radius:14px; padding:10px 16px; min-width:110px;">'
                    f'<div style="font-size:13px; color:#888;">{label}</div>'
                    f'<div style="font-size:20px; font-weight:700; color:#1B4E8F;">{value}</div></div>'
                    for label, value in [
                        ("힌트 사용 횟수", f'{summary["total_hints_used"]}회'),
                        ("쉬운 문제 정답률", f'{summary["accuracy_by_difficulty"].get("쉬움")}%'
                         if summary["accuracy_by_difficulty"].get("쉬움") is not None else "-"),
                        ("중간 난이도 정답률", f'{summary["accuracy_by_difficulty"].get("중간")}%'
                         if summary["accuracy_by_difficulty"].get("중간") is not None else "-"),
                        ("고난이도 정답률", f'{summary["accuracy_by_difficulty"].get("어려움")}%'
                         if summary["accuracy_by_difficulty"].get("어려움") is not None else "-"),
                    ]
                )
                + "</div></div>", unsafe_allow_html=True)

    items = feedback["items"]
    if not items:
        return

    for item in items:
        color = MASTERY_COLOR.get(item["mastery_level"], "#999")
        width = mastery_bar_width(item["avg_hints_used"]) if item["avg_hints_used"] is not None else 0
        revealed_count = item.get("revealed_count", 0)

        if item["problems_attempted"] > 0:
            solved_line = f"평균 힌트 {item['avg_hints_used']}개 · 스스로 해결 {item['problems_attempted']}문제"
        else:
            solved_line = "아직 스스로 끝까지 해결한 문제가 없어요"
        if revealed_count:
            solved_line += f' <span style="color:#D9534F;">· 정답 공개 {revealed_count}문제</span>'
        solved_line += f' <span style="color:#AAA;">(성공률 {item.get("success_rate", 0)}%)</span>'

        diff_acc = item.get("accuracy_by_difficulty") or {}
        diff_line = " · ".join(
            f"{label} {diff_acc.get(key)}%" if diff_acc.get(key) is not None else f"{label} -"
            for label, key in [("쉬움", "쉬움"), ("중간", "중간"), ("어려움", "어려움")]
        )

        st.markdown(
            f"""
            <div class="mastery-card">
              <div style="display:flex; justify-content:space-between; align-items:center;">
                <div style="font-size:20px; font-weight:700;">{html_lib.escape(item['unit'])}</div>
                <div class="mastery-tag" style="background:{color}22; color:{color};">
                  {item['mastery_level']}
                </div>
              </div>
              <div class="mastery-bar-track">
                <div class="mastery-bar-fill" style="width:{width}%; background:{color};"></div>
              </div>
              <div style="color:#888; font-size:15px;">
                {solved_line}
              </div>
              <div style="color:#AAA; font-size:13px; margin-top:6px;">
                난이도별 정답률 — {diff_line}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    weakest = feedback.get("weakest_unit")
    if weakest:
        st.markdown(
            f"""
            <div class="recommend-banner">
              <div style="font-size:18px; color:#1B4E8F; font-weight:600;">
                {html_lib.escape(weakest)}가 가장 약해요.<br>이 단원 문제를 더 풀어볼까요?
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(f"📝 {weakest} 문제 풀기 →"):
            st.session_state.preselect_unit = weakest
            st.info("왼쪽 사이드바에서 '💬 학습'을 눌러 문제를 풀어보세요!")


if page == "💬 학습":
    render_study_page()
else:
    render_feedback_page()
