from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st


KAKAO_BUTTON_PATH = Path(__file__).resolve().parent / "assets" / "kakao_login_medium_wide.png"


def _clear_login_query() -> None:
    if "login" in st.query_params:
        del st.query_params["login"]
    if "kakao" in st.query_params:
        del st.query_params["kakao"]


@st.cache_data
def _kakao_button_data_uri() -> str:
    encoded = base64.b64encode(KAKAO_BUTTON_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


@st.dialog(" ", width="small", on_dismiss=_clear_login_query)
def _login_dialog() -> None:
    st.html(
        f"""
        <div class="login-modal-content">
            <div class="login-modal-title">로그인하고 리뷰를 남겨보세요.</div>
            <a class="kakao-login-image-button" href="?login=1&kakao=1" target="_self" aria-label="카카오 로그인">
                <img src="{_kakao_button_data_uri()}" alt="카카오 로그인" />
            </a>
            <div class="login-modal-help">로그인하면 리뷰 작성과 좋아요를 사용할 수 있습니다.</div>
        </div>
        """,
    )


def render_login_entry() -> None:
    st.html(
        """
        <a
            class="top-login-link"
            href="?login=1"
            target="_self"
            style="position:fixed;top:18px;right:28px;z-index:2147483000;height:34px;display:inline-flex;align-items:center;justify-content:center;padding:0 4px;border:0;background:transparent;color:#333333;font-size:15px;font-weight:760;line-height:34px;text-decoration:none;box-shadow:none;"
        >로그인</a>
        """,
    )
    if st.query_params.get("login") == "1":
        _login_dialog()
