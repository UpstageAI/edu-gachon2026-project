from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote_plus

import streamlit as st

from constants import EXAMPLE_PROMPTS


def render_app_header(service_name: str, message_count: int = 0) -> None:
    count_label = f"{message_count} messages" if message_count else "ready"
    st.html(
        f"""
        <div class="app-header">
            <div class="brand-row">
                <div class="brand-mark" aria-hidden="true">H</div>
                <div>
                    <div class="service-name">{html.escape(service_name)}</div>
                    <div class="service-caption">건강한 한 끼를 빠르게 정리합니다</div>
                </div>
            </div>
            <div class="header-meta">
                <span class="status-dot" aria-hidden="true"></span>
                <span>{html.escape(count_label)}</span>
            </div>
        </div>
        """,
    )


def render_empty_state() -> None:
    st.html(
        """
        <section class="empty-state">
            <div class="empty-kicker">AI meal planner</div>
            <h1>오늘 한 끼를 어떻게 맞출까요?</h1>
            <p>칼로리, 제외할 재료, 선호하는 맛을 말하면 바로 식단과 영양 정보를 정리해드릴게요.</p>
        </section>
        """,
    )


def render_suggestion_buttons() -> str | None:
    return st.pills(
        "추천 질문",
        EXAMPLE_PROMPTS,
        selection_mode="single",
        key="example_prompt_choice",
        label_visibility="collapsed",
        width="stretch",
    )


def render_message(message: dict) -> None:
    role = message.get("role", "assistant")
    role_label = "나" if role == "user" else "Healthy Meal Agent"
    content = message.get("content", "")
    attachments = message.get("attachments", [])

    attachment_html = ""
    if attachments:
        chips = "".join(
            f'<span class="attachment-chip">{html.escape(name)}</span>' for name in attachments
        )
        attachment_html = f'<div class="attachment-list">{chips}</div>'

    st.html(
        f"""
        <div class="message-row {html.escape(role)}">
            <div class="message-stack">
                <div class="message-meta">
                    <span>{html.escape(role_label)}</span>
                </div>
                <div class="message-bubble">
                    {_markdownish_to_html(content)}
                    {attachment_html}
                </div>
            </div>
        </div>
        """,
    )

    if role == "assistant":
        render_meal_card(message.get("agent"))


def render_typing_indicator() -> None:
    st.html(
        """
        <div class="typing-row" aria-live="polite" aria-label="답변 생성 중">
            <div class="typing-bubble">
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
            </div>
        </div>
        """,
    )


def render_progress_step(message: str) -> None:
    """추천 파이프라인의 현재 단계를 실시간으로 보여준다(SSE로 받은 문구).

    점 3개 애니메이션 옆에 '건강 조건을 분석하고 있어요…' 같은 단계 문구를 붙여,
    사용자가 '지금 무엇을 하는 중'인지 알 수 있게 한다.
    """
    st.html(
        f"""
        <div class="typing-row" aria-live="polite" aria-label="추천 진행 상황">
            <div class="progress-bubble">
                <span class="progress-dots">
                    <span class="typing-dot"></span>
                    <span class="typing-dot"></span>
                    <span class="typing-dot"></span>
                </span>
                <span class="progress-text">{html.escape(message)}</span>
            </div>
        </div>
        """,
    )


def render_message_stream_spacer() -> None:
    st.html("""<div class="message-stream-spacer" aria-hidden="true"></div>""")


def render_meal_card(agent_payload: dict | None) -> None:
    if not agent_payload:
        return

    meal_plan = agent_payload.get("meal_plan")
    nutrition = agent_payload.get("nutrition_total")
    validation = agent_payload.get("validation_result") or {}
    if not meal_plan or not nutrition:
        return

    items = meal_plan.get("items", [])
    warnings = validation.get("warnings", [])
    status = validation.get("status", "PASS")
    status_class = (
        "warning" if status == "PASS_WITH_WARNING" else "fail" if status == "FAIL" else ""
    )
    status_label = {
        "PASS": "적합",
        "PASS_WITH_WARNING": "주의",
        "FAIL": "조정 필요",
    }.get(status, "분석")

    # 주인공은 '무엇을 먹는가'(식단). 음식은 크게, 칼로리·영양은 아래 근거 띠로.
    food_rows = "".join(
        f"""
        <div class="food-row">
            <span class="role-badge {_role_class(item.get("meal_role"))}">\
{html.escape(item.get("meal_role", ""))}</span>
            <span class="food-name">{html.escape(item.get("food_name", "음식"))}</span>
            <span class="food-figures">{_num(item.get("kcal"))}<em>kcal</em>\
 · 나트륨 {_num(item.get("sodium"))}<em>mg</em></span>
        </div>
        """
        for item in items
    )
    warning_html = ""
    if warnings:
        items_html = "".join(f"<li>{html.escape(w)}</li>" for w in warnings)
        warning_html = (
            '<div class="warning-list"><span class="warning-cap">주의</span>'
            f"<ul>{items_html}</ul></div>"
        )

    # 카드: 제목 → 음식(주인공, 크게) → 영양 근거 띠 → 경고.
    # 레시피는 st.expander(위젯)라 HTML 문자열 안에 못 넣으므로 카드 '아래'에 이어 붙인다.
    kcal = _num(nutrition.get("total_kcal"))
    st.html(
        f"""
        <div class="meal-card">
            <div class="meal-card-title">
                <strong>{html.escape(meal_plan.get("meal_type", "추천"))} 추천 식단</strong>
                <span class="status-pill {status_class}">{html.escape(status_label)}</span>
            </div>
            <div class="food-list">{food_rows}</div>
            <div class="nutri-strip">
                <div class="nutri-total">
                    <span class="nutri-total-num">{kcal}</span>
                    <span class="nutri-total-unit">kcal</span>
                </div>
                <div class="nutri-macros">
                    {_macro_chip("탄수", _num(nutrition.get("total_carbohydrate")), "g")}
                    {_macro_chip("단백", _num(nutrition.get("total_protein")), "g")}
                    {_macro_chip("지방", _num(nutrition.get("total_fat")), "g")}
                    {_macro_chip("나트륨", _num(nutrition.get("total_sodium")), "mg")}
                </div>
            </div>
            {warning_html}
        </div>
        """,
    )

    # ── 음식별 레시피 (기본 접힘) ──
    # 추천 결과만 먼저 깔끔히 보여주고, 궁금한 음식만 골라 펼치게 한다(정보 과부하 방지).
    recipe_items = [it for it in items if _has_recipe(it)]
    if recipe_items:
        with st.container(key=f"recipe-wrap-{id(items)}"):
            st.html('<div class="recipe-section-label">레시피 · 만드는 법</div>')
            for item in recipe_items:
                _render_recipe_expander(item)


def _has_recipe(item: dict) -> bool:
    """펼칠 만한 레시피(단계 또는 사진)가 있는 음식인지."""
    return bool(item.get("recipe_steps")) or bool(item.get("recipe_images"))


def _proxied(url: str) -> str:
    """원본 이미지 URL을 우리 백엔드 프록시(+캐시) 경로로 감싼다.

    원본(foodsafetykorea)은 사진 폭주 시 IP를 rate-limit으로 막는다. 백엔드가 한 번만
    받아 캐시하므로 브라우저는 우리 서버에서만 로드 → 모든 단계 사진을 순서대로 보여줄 수 있다.
    """
    # 브라우저가 직접 로드하는 <img> 소스라, 서버-서버용(API_BASE_URL, 배포 시 http://api:8000)이
    # 아니라 브라우저가 접근 가능한 공개 주소(PUBLIC_API_BASE_URL)를 써야 한다.
    from api_client import PUBLIC_API_BASE_URL

    return f"{PUBLIC_API_BASE_URL}/api/v1/recipe-image?url={quote_plus(url)}"


def _youtube_search_url(food_name: str) -> str:
    """'○○ 레시피'로 유튜브 검색결과로 바로 이동하는 URL (API 불필요)."""
    return f"https://www.youtube.com/results?search_query={quote_plus(food_name + ' 레시피')}"


def _render_recipe_expander(item: dict) -> None:
    """음식 하나의 레시피를 접힌 expander로. 펼치면 사진+단계+나트륨팁+유튜브 링크."""
    name = item.get("food_name", "음식")
    steps = item.get("recipe_steps") or []
    images = item.get("recipe_images") or []
    ingredients = (item.get("ingredients") or "").strip()
    na_tip = (item.get("na_tip") or "").strip()

    # expander 내부는 st.html '한 덩어리'로 그린다.
    # (블록마다 st.html을 쪼개면 Streamlit이 각각 컨테이너로 감싸 세로 간격이 들쭉날쭉해짐)
    sections: list[str] = []

    # 재료 (첫 줄은 음식명 반복이라 버리고 실제 재료 줄만)
    ing_body = _ingredients_body(ingredients)
    if ing_body:
        sections.append(
            '<div class="recipe-block"><div class="recipe-block-label">재료</div>'
            f'<div class="recipe-ingredients">{html.escape(ing_body)}</div></div>'
        )

    # 조리 단계 — 사진과 글을 순서대로 나란히(단계1 사진+글, 단계2 사진+글...).
    # 사진은 백엔드 프록시(+캐시)로 로드해 원본 rate-limit을 피하고 전부 보여준다.
    if steps:
        rows = "".join(
            _step_row(idx, _clean_step(step), images[idx] if idx < len(images) else None)
            for idx, step in enumerate(steps)
        )
        sections.append(
            '<div class="recipe-block"><div class="recipe-block-label">만드는 법</div>'
            f'<div class="recipe-steps">{rows}</div></div>'
        )

    # 나트륨 저감 팁
    if na_tip:
        sections.append(
            f'<div class="recipe-tip"><span class="recipe-tip-icon">🧂</span>'
            f"<span>{html.escape(na_tip)}</span></div>"
        )

    # 유튜브에서 보기 — 검색결과로 이동
    sections.append(
        f'<a class="recipe-youtube" href="{_youtube_search_url(name)}" '
        f'target="_blank" rel="noopener noreferrer">'
        f'<span class="recipe-youtube-icon">▶</span>'
        f"유튜브에서 '{html.escape(name)}' 레시피 보기</a>"
    )

    with st.expander(f"🍳 {name} 레시피 보기"):
        st.html(f'<div class="recipe-body">{"".join(sections)}</div>')


def _step_row(idx: int, text: str, image_url: str | None) -> str:
    """조리 단계 한 줄: 왼쪽 번호+사진, 오른쪽 설명. 사진 없으면 번호만."""
    photo = ""
    if image_url:
        photo = (
            f'<img class="step-photo" src="{html.escape(_proxied(image_url))}" '
            f'alt="" loading="lazy" onerror="this.style.visibility=\'hidden\'">'
        )
    return (
        '<div class="recipe-step">'
        f'<div class="step-figure"><span class="step-no">{idx + 1}</span>{photo}</div>'
        f'<div class="step-text">{html.escape(text)}</div>'
        "</div>"
    )


def _ingredients_body(raw: str) -> str:
    """재료 원문에서 첫 줄(음식명 반복)을 떼고 실제 재료 줄만 반환."""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) >= 2:
        return " ".join(lines[1:])
    return lines[0] if lines else ""


def _clean_step(step: str) -> str:
    """조리 단계 문자열 정리. <ol>이 번호를 붙이므로 앞 번호와 끝 잔여표식을 뗀다."""
    s = step.strip()
    # 앞머리 "1.", "2)", "1 " 같은 번호 제거 (<ol>이 자동 번호를 붙이므로 중복 방지)
    s = re.sub(r"^\s*\d+\s*[.)]?\s*", "", s)
    # 삼삼한밥상 데이터는 단계 끝에 'a','b' 같은 단일 알파벳 표식이 붙어 있음 → 제거.
    return re.sub(r"[a-z]$", "", s).strip()


def _macro_chip(label: str, value: str, unit: str) -> str:
    """총 열량 옆 보조 지표(탄단지·나트륨) 한 칸."""
    return (
        '<div class="macro-chip">'
        f'<span class="macro-label">{html.escape(label)}</span>'
        f'<span class="macro-value">{html.escape(value)}<em>{html.escape(unit)}</em></span>'
        "</div>"
    )


# meal_role → 뱃지 색 클래스. 역할이 한눈에 구분되게 색을 나눈다.
_ROLE_CLASS = {
    "밥": "role-rice",
    "국물": "role-soup",
    "반찬": "role-side",
    "한그릇": "role-bowl",
    "간식": "role-snack",
}


def _role_class(role: str | None) -> str:
    return _ROLE_CLASS.get(role or "", "role-etc")


def _num(value: Any) -> str:
    try:
        return f"{float(value):.0f}"
    except (TypeError, ValueError):
        return "0"


def _markdownish_to_html(text: str) -> str:
    if not text:
        return ""

    parts = re.split(r"```", text)
    rendered: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 0:
            rendered.append(_text_to_html(part))
        else:
            rendered.append(_code_to_html(part))
    return "".join(rendered)


def _text_to_html(text: str) -> str:
    escaped = html.escape(text.strip("\n"))
    return escaped.replace("\n", "<br>")


def _code_to_html(block: str) -> str:
    lines = block.strip("\n").splitlines()
    if lines and re.fullmatch(r"[A-Za-z0-9_+.#-]{1,24}", lines[0].strip()):
        code = "\n".join(lines[1:])
    else:
        code = "\n".join(lines)
    return f"<pre><code>{html.escape(code)}</code></pre>"
