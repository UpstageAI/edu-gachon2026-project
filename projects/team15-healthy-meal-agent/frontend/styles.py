from __future__ import annotations

import streamlit as st


def inject_global_styles() -> None:
    st.html(
        """
        <style>
        :root {
            --bg: #fcfdfd;
            --surface: #ffffff;
            --surface-muted: #f2f5f5;
            --line: #e5e8eb;
            --line-strong: #d1d6db;
            --text: #333333;
            --muted: #6b7684;
            --muted-2: #8b95a1;
            --accent: #4aa49b;
            --accent-soft: #e7f7f5;
            --blue: #4aa49b;
            --blue-soft: #e7f7f5;
            --teal: #7fe7dc;
            --teal-ink: #12413d;
            --user-bubble: #edf8f6;
            --user-bubble-line: #c8ebe7;
            --user-bubble-text: #183f3b;
            --sidebar-bg: #f8fafc;
            --kakao: #fee500;
            --warning: #b7791f;
            --warning-bg: #fff7e6;
            --danger: #d92d20;
            --danger-bg: #fff1f0;
            --radius-lg: 20px;
            --radius-md: 16px;
            --radius-sm: 14px;
            --shadow-sm: 0 1px 2px rgba(25, 28, 33, 0.06);
            --shadow-md: 0 10px 32px rgba(25, 28, 33, 0.08);
            --shadow-float: 0 28px 90px rgba(48, 65, 76, 0.13);
        }

        .stApp {
            background:
                linear-gradient(180deg, #ffffff 0%, #f6fbff 48%, #fcfdfd 100%),
                var(--bg);
            color: var(--text);
        }

        header.stAppHeader,
        header[data-testid="stHeader"],
        .stAppHeader,
        [class*="stAppHeader"],
        [data-testid="stHeader"],
        [data-testid="stToolbar"] {
            display: block !important;
            height: 0 !important;
            min-height: 0 !important;
            max-height: 0 !important;
            padding: 0 !important;
            margin: 0 !important;
            overflow: visible !important;
            visibility: visible !important;
            background: transparent !important;
            border: 0 !important;
            box-shadow: none !important;
            pointer-events: none !important;
        }

        [data-testid="stDecoration"],
        [data-testid="stStatusWidget"],
        [data-testid="stToolbarActions"],
        [data-testid="stAppDeployButton"],
        [data-testid="stMainMenu"],
        [data-testid="stMainMenuButton"],
        footer {
            display: none !important;
            height: 0 !important;
            min-height: 0 !important;
            max-height: 0 !important;
            padding: 0 !important;
            margin: 0 !important;
            overflow: hidden !important;
            position: absolute !important;
            top: -9999px !important;
            visibility: hidden !important;
            background: transparent !important;
            border: 0 !important;
            box-shadow: none !important;
        }

        .stMain,
        [data-testid="stMain"],
        [data-testid="stAppViewContainer"],
        [data-testid="stAppViewContainer"] > .main,
        section.main {
            background: transparent !important;
        }

        [data-testid="stAppViewContainer"] > .main .block-container,
        .block-container {
            width: 100% !important;
            max-width: none !important;
            min-height: 100vh !important;
            margin: 0 !important;
            padding: 0 32px 132px !important;
        }

        [data-testid="stMainBlockContainer"]:has(.st-key-welcome_stage),
        .block-container:has(.st-key-welcome_stage) {
            padding-left: 0 !important;
            padding-right: 0 !important;
        }

        .top-login-link {
            position: fixed;
            top: 18px;
            right: 28px;
            z-index: 2147483000;
            height: 34px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0 4px;
            border: 0;
            border-radius: 0 !important;
            background: transparent;
            color: var(--text);
            font-size: 15px;
            font-weight: 760;
            line-height: 34px;
            text-decoration: none !important;
            box-shadow: none !important;
        }

        .top-login-link:hover {
            color: var(--teal-ink) !important;
            background: transparent !important;
            text-decoration: none !important;
        }

        div[role="dialog"],
        section[role="dialog"],
        dialog[role="dialog"] {
            position: fixed !important;
            inset: auto !important;
            top: 50% !important;
            left: 50% !important;
            transform: translate(-50%, -50%) !important;
            width: min(380px, calc(100vw - 32px)) !important;
            min-height: 164px !important;
            margin: 0 !important;
            border: 0 !important;
            border-radius: 16px !important;
            background: var(--surface) !important;
            box-shadow: 0 18px 48px rgba(25, 28, 33, 0.2) !important;
            overflow: hidden !important;
        }

        [data-testid="stDialog"] {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            padding: 0 !important;
            background: rgba(149, 168, 187, 0.25) !important;
            overflow: hidden !important;
        }

        [data-testid="stDialog"] > div {
            width: min(380px, calc(100vw - 32px)) !important;
            min-height: 164px !important;
            margin: 0 !important;
            border: 0 !important;
            border-radius: 16px !important;
            background: var(--surface) !important;
            box-shadow: 0 18px 48px rgba(25, 28, 33, 0.2) !important;
            overflow: hidden !important;
        }

        div[role="dialog"] > div,
        section[role="dialog"] > div,
        dialog[role="dialog"] > div {
            padding: 0 !important;
        }

        div[role="dialog"] [data-testid="stDialog"],
        section[role="dialog"] [data-testid="stDialog"],
        dialog[role="dialog"] [data-testid="stDialog"] {
            position: static !important;
            inset: auto !important;
            transform: none !important;
            width: 100% !important;
            min-height: 0 !important;
            margin: 0 !important;
            border-radius: 0 !important;
            background: transparent !important;
            box-shadow: none !important;
        }

        div[role="dialog"] h2,
        section[role="dialog"] h2,
        section[role="dialog"] [data-testid="stDialogHeader"],
        div[role="dialog"] [data-testid="stDialogHeader"] {
            position: absolute !important;
            inset: 0 0 auto 0 !important;
            min-height: 0 !important;
            height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
            background: transparent !important;
            border: 0 !important;
        }

        div[role="dialog"] [aria-label="Close"],
        section[role="dialog"] [aria-label="Close"],
        [data-testid="stDialog"] [aria-label="Close"] {
            position: absolute !important;
            top: 17px !important;
            right: 17px !important;
            z-index: 2 !important;
            width: 28px !important;
            height: 28px !important;
            min-width: 28px !important;
            border-radius: 999px !important;
            background: #f0f3f6 !important;
            color: #8a939e !important;
            box-shadow: none !important;
        }

        [data-testid="stDialog"] [aria-label="무시"],
        [data-testid="stDialog"] [aria-label="Dismiss"] {
            display: none !important;
            visibility: hidden !important;
            pointer-events: none !important;
        }

        .login-modal-content {
            width: 100%;
            min-height: 148px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: flex-start;
            gap: 13px;
            padding: 24px 24px 18px;
        }

        .login-modal-title {
            width: 100%;
            padding-right: 36px;
            color: #20252b;
            font-size: 16px;
            font-weight: 850;
            line-height: 1.35;
            text-align: left;
        }

        .kakao-login-image-button {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 300px;
            height: 45px;
            border: 0;
            border-radius: 3px;
            background: transparent;
            box-shadow: none;
            line-height: 0;
            text-decoration: none;
        }

        .login-modal-help {
            color: #77818c;
            font-size: 11px;
            font-weight: 650;
            line-height: 1.45;
            text-align: center;
        }

        .kakao-login-image-button img {
            display: block;
            width: 300px;
            height: 45px;
            object-fit: contain;
        }

        [data-testid="stSidebar"] {
            width: 288px !important;
            min-width: 288px !important;
            background: var(--sidebar-bg);
            border-right: 1px solid #edf1f5;
            box-shadow: none;
        }

        [data-testid="stSidebar"][aria-expanded="false"] {
            width: 0 !important;
            min-width: 0 !important;
            max-width: 0 !important;
            flex: 0 0 0 !important;
            border-right: 0 !important;
            box-shadow: none !important;
            overflow: visible !important;
            transform: none !important;
        }

        [data-testid="stSidebar"][aria-expanded="false"] > div,
        [data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarContent"] {
            width: 0 !important;
            min-width: 0 !important;
            max-width: 0 !important;
            padding: 0 !important;
            overflow: hidden !important;
            visibility: hidden !important;
        }

        [data-testid="stSidebar"][aria-expanded="false"] ~ [data-testid="stMain"] {
            width: 100vw !important;
            max-width: 100vw !important;
            flex: 0 0 100vw !important;
            margin-left: 0 !important;
            transform: none !important;
        }

        [data-testid="stSidebar"][aria-expanded="false"] ~ [data-testid="stMain"] .block-container {
            width: 100vw !important;
            max-width: 100vw !important;
            padding-left: 0 !important;
            padding-right: 0 !important;
        }

        [data-testid="stSidebar"] > div {
            background: var(--sidebar-bg) !important;
            padding-top: 18px !important;
        }

        [data-testid="stSidebarContent"] {
            padding: 0 10px 12px !important;
        }

        button[data-testid="stSidebarCollapsedControl"],
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="stExpandSidebarButton"],
        [data-testid="stExpandSidebarButton"] button,
        [data-testid="stSidebarCollapseButton"],
        [data-testid="stSidebarCollapseButton"] button {
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            visibility: visible !important;
            opacity: 1 !important;
            pointer-events: auto !important;
            z-index: 2147483001 !important;
            width: 38px !important;
            height: 38px !important;
            min-width: 38px !important;
            border-radius: 999px !important;
            background: rgba(255, 255, 255, 0.84) !important;
            border: 1px solid rgba(209, 214, 219, 0.72) !important;
            box-shadow: var(--shadow-sm) !important;
            backdrop-filter: blur(12px);
        }

        button[data-testid="stSidebarCollapsedControl"],
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="stExpandSidebarButton"] {
            position: fixed !important;
            top: 16px !important;
            left: 16px !important;
        }

        [data-testid="stSidebarCollapseButton"] {
            position: absolute !important;
            top: 18px !important;
            right: 10px !important;
        }

        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
            gap: 0.32rem;
        }

        .sidebar-brand {
            padding: 8px 4px 14px;
            display: flex;
            align-items: center;
            gap: 9px;
        }

        .sidebar-brand::before {
            content: "M";
            width: 24px;
            height: 24px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 8px;
            color: #ffffff;
            background: linear-gradient(135deg, #4aa49b, #6c8fe8);
            font-size: 13px;
            font-weight: 850;
            flex: 0 0 auto;
        }

        .sidebar-title {
            color: var(--text);
            font-size: 17px;
            font-weight: 760;
            line-height: 1.2;
        }

        .sidebar-caption {
            display: none;
            margin-top: 5px;
            color: var(--muted);
            font-size: 13px;
            line-height: 1.45;
        }

        .sidebar-section-label {
            margin: 10px 0 2px;
            color: var(--muted-2);
            font-size: 12px;
            font-weight: 800;
        }

        .sidebar-empty {
            padding: 12px;
            border-radius: 10px;
            color: var(--muted);
            font-size: 13px;
            background: var(--surface-muted);
        }

        [data-testid="stSidebar"] .stButton > button {
            min-height: 36px;
            justify-content: flex-start;
            border-radius: 999px;
            border: 0 !important;
            background: transparent;
            color: var(--text);
            font-size: 13px;
            font-weight: 650;
            box-shadow: none;
        }

        [data-testid="stSidebar"] .stButton > button[kind="primary"],
        [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {
            background: #edf3f7 !important;
            color: var(--text) !important;
            font-weight: 760 !important;
        }

        [data-testid="stSidebar"] .stButton > button:hover,
        [data-testid="stSidebar"] .stButton > button:focus {
            background: #ebeef2 !important;
            color: var(--text) !important;
        }

        [data-testid="stSidebar"] [role="radiogroup"] {
            gap: 2px;
        }

        [data-testid="stSidebar"] [role="radiogroup"] label {
            min-height: 36px;
            padding: 7px 10px !important;
            border-radius: 10px;
            border: 0 !important;
            background: transparent;
            transition: background 120ms ease, box-shadow 120ms ease;
        }

        [data-testid="stSidebar"] [role="radiogroup"] label:hover {
            background: var(--surface-muted);
        }

        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
            background: #e8f0fe;
            box-shadow: none;
        }

        [data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {
            display: none;
        }

        [data-testid="stSidebar"] [role="radiogroup"] p {
            font-size: 13px;
            font-weight: 650;
            color: var(--text);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {
            color: #263238;
            font-weight: 750;
        }

        [data-testid="stSidebar"] [data-testid="stTextInput"] input {
            min-height: 36px !important;
            border: 0 !important;
            border-radius: 999px !important;
            background: #ffffff !important;
            box-shadow: none !important;
            font-size: 13px !important;
        }

        .stButton > button:focus-visible,
        textarea:focus,
        input:focus {
            outline: 3px solid rgba(127, 231, 220, 0.34) !important;
            outline-offset: 2px;
            border-color: var(--teal) !important;
        }

        [data-testid="stBottom"],
        [data-testid="stBottomBlockContainer"],
        .stBottomBlockContainer {
            position: fixed !important;
            inset: auto 0 0 0 !important;
            z-index: 2147482500 !important;
            width: 100% !important;
            background: transparent !important;
            border: 0 !important;
            box-shadow: none !important;
            pointer-events: none;
        }

        [data-testid="stBottom"]::before,
        [data-testid="stBottom"]::after,
        [data-testid="stBottomBlockContainer"]::before,
        [data-testid="stBottomBlockContainer"]::after,
        .stBottomBlockContainer::before,
        .stBottomBlockContainer::after {
            display: none !important;
            content: none !important;
        }

        [data-testid="stBottom"] *,
        [data-testid="stBottomBlockContainer"] *,
        .stBottomBlockContainer * {
            box-shadow: none !important;
        }

        [data-testid="stBottom"] > div,
        [data-testid="stBottomBlockContainer"] > div,
        .stBottomBlockContainer > div {
            max-width: 820px !important;
            margin: 0 auto 28px !important;
            padding: 0 24px !important;
            background: transparent !important;
            border: 0 !important;
            box-shadow: none !important;
            pointer-events: auto;
        }

        [data-testid="stChatInput"] {
            max-width: 820px;
            margin: 0 auto;
            padding: 0 !important;
            min-height: 56px !important;
            height: 56px !important;
            background: transparent !important;
        }

        .st-key-inline_composer {
            width: min(680px, 100%);
            max-width: 680px;
            margin: 24px auto 0;
        }

        .st-key-welcome_stage {
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            width: 100vw;
            max-width: 100vw;
            padding: 0 0 92px;
        }

        .st-key-welcome_stage [data-testid="stVerticalBlock"] {
            width: min(760px, 100%);
            margin: 0 auto;
            gap: 0.85rem;
        }

        .st-key-welcome_stage [data-testid="stChatInput"] {
            max-width: 680px;
            height: 58px !important;
            min-height: 58px !important;
        }

        [data-testid="stChatInput"] > div,
        [data-testid="stChatInput"] > div:focus-within {
            position: relative !important;
            padding: 0 !important;
            border: 0 !important;
            background: transparent !important;
            box-shadow: none !important;
            outline: none !important;
        }

        [data-testid="stChatInput"] textarea {
            min-height: 56px !important;
            height: 56px !important;
            padding: 15px 62px 15px 28px !important;
            border-radius: 999px !important;
            border: 1px solid var(--line-strong) !important;
            background: rgba(255, 255, 255, 0.96) !important;
            color: var(--text) !important;
            font-size: 15px !important;
            line-height: 1.45 !important;
            box-shadow: 0 1px 2px rgba(35, 62, 75, 0.06) !important;
            backdrop-filter: none !important;
        }

        .st-key-welcome_stage [data-testid="stChatInput"] textarea {
            min-height: 58px !important;
            height: 58px !important;
            padding: 16px 64px 16px 28px !important;
            border: 1px solid rgba(229, 232, 235, 0.86) !important;
            border-radius: 999px !important;
            background: rgba(255, 255, 255, 0.94) !important;
            font-size: 15px !important;
            box-shadow: 0 1px 2px rgba(37, 63, 78, 0.06) !important;
            backdrop-filter: none !important;
        }

        [data-testid="stChatInput"] textarea::placeholder {
            color: var(--muted-2);
            opacity: 1;
        }

        [data-testid="stChatInput"] button {
            position: absolute !important;
            top: 9px !important;
            z-index: 5 !important;
            width: 38px !important;
            height: 38px !important;
            min-width: 38px !important;
            border-radius: 999px !important;
            box-shadow: none !important;
        }

        .st-key-welcome_stage [data-testid="stChatInput"] button {
            top: 10px !important;
            width: 42px !important;
            height: 42px !important;
            min-width: 42px !important;
        }

        [data-testid="stChatInput"] button[aria-label="Upload a file"],
        [data-testid="stChatInputFileUploadButton"] {
            display: none !important;
            visibility: hidden !important;
            pointer-events: none !important;
        }

        [data-testid="stChatInput"] button[data-testid="stChatInputSubmitButton"] {
            right: 10px !important;
            background: #eef4f3 !important;
            color: var(--teal-ink) !important;
            border: 0 !important;
        }

        .st-key-welcome_stage [data-testid="stChatInput"] button[data-testid="stChatInputSubmitButton"] {
            right: 10px !important;
        }

        [data-testid="stChatInput"] button:disabled {
            background: #eef4f3 !important;
            color: var(--muted-2) !important;
        }

        .app-header {
            display: none !important;
            align-items: center;
            justify-content: space-between;
            gap: 18px;
            max-width: 920px;
            min-height: 58px;
            padding: 12px 16px;
            margin: 0 auto 10px;
            border: 1px solid var(--line);
            border-radius: var(--radius-md);
            background: var(--surface);
            box-shadow: var(--shadow-sm);
        }

        .st-key-conversation_shell {
            width: min(820px, 100%);
            margin: 72px auto 0;
        }

        .st-key-message_stream {
            width: 100%;
            min-height: calc(100vh - 210px);
            padding-bottom: 128px;
        }

        .message-stream-spacer {
            height: 152px;
            min-height: 152px;
            pointer-events: none;
        }

        .brand-row {
            display: flex;
            align-items: center;
            gap: 12px;
            min-width: 0;
        }

        .brand-mark {
            width: 34px;
            height: 34px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 14px;
            background: var(--blue);
            color: #fff;
            font-weight: 800;
        }

        .service-name {
            color: var(--text);
            font-size: 15px;
            font-weight: 780;
            line-height: 1.2;
        }

        .service-caption {
            margin-top: 2px;
            color: var(--muted);
            font-size: 12px;
            font-weight: 650;
            line-height: 1.35;
        }

        .header-meta {
            flex: 0 0 auto;
            display: flex;
            align-items: center;
            gap: 8px;
            color: var(--muted);
            font-size: 13px;
            font-weight: 650;
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 999px;
            background: var(--blue);
        }

        .empty-state {
            max-width: 760px;
            display: flex;
            flex-direction: column;
            align-items: center;
            text-align: center;
            padding: 0 18px 14px;
            margin: 0 auto;
        }

        .empty-kicker {
            margin-bottom: 12px;
            padding: 7px 11px;
            border-radius: 999px;
            border: 1px solid var(--line);
            background: var(--surface);
            color: var(--teal-ink);
            font-size: 12px;
            font-weight: 800;
            box-shadow: var(--shadow-sm);
        }

        .empty-state h1 {
            margin: 0;
            color: var(--text);
            font-size: 35px;
            line-height: 1.18;
            font-weight: 680;
        }

        .empty-state p {
            max-width: 560px;
            margin: 12px auto 0;
            color: var(--muted);
            font-size: 16px;
            line-height: 1.65;
        }

        .st-key-example_prompt_choice {
            width: min(680px, 100%);
            max-width: 680px;
            margin: 14px auto 0;
        }

        .st-key-example_prompt_choice [role="radiogroup"],
        .st-key-example_prompt_choice [data-baseweb="radio"] {
            justify-content: center;
            gap: 10px;
        }

        .st-key-example_prompt_choice button,
        .st-key-example_prompt_choice label {
            min-height: 42px;
            border-radius: 999px !important;
            border-color: transparent !important;
            background: rgba(242, 244, 246, 0.68) !important;
            color: var(--text) !important;
            font-size: 14px !important;
            font-weight: 620 !important;
            box-shadow: none !important;
        }

        .st-key-example_prompt_choice button:hover,
        .st-key-example_prompt_choice label:hover {
            border-color: transparent !important;
            background: rgba(255, 255, 255, 0.86) !important;
            color: var(--text) !important;
            box-shadow: var(--shadow-sm) !important;
        }

        .message-row {
            display: flex;
            width: 100%;
            margin: 16px 0;
            animation: rise-in 220ms ease both;
        }

        .message-row.user {
            justify-content: flex-end;
        }

        .message-row.assistant {
            justify-content: flex-start;
        }

        .message-stack {
            width: min(78%, 760px);
        }

        .message-row.user .message-stack {
            width: min(68%, 680px);
        }

        .message-meta {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            margin: 0 4px 7px;
            color: var(--muted-2);
            font-size: 12px;
            font-weight: 750;
        }

        .message-bubble {
            padding: 15px 17px;
            border-radius: var(--radius-md);
            line-height: 1.72;
            font-size: 15px;
            overflow-wrap: anywhere;
            word-break: keep-all;
        }

        .message-row.assistant .message-bubble {
            border: 1px solid var(--line);
            background: var(--surface);
            color: var(--text);
            box-shadow: var(--shadow-sm);
        }

        .message-row.user .message-bubble {
            border: 1px solid var(--user-bubble-line) !important;
            background: var(--user-bubble) !important;
            color: var(--user-bubble-text) !important;
            box-shadow: 0 12px 34px rgba(71, 144, 137, 0.12) !important;
        }

        .message-bubble pre {
            margin: 12px 0 4px;
            padding: 13px;
            overflow-x: auto;
            border-radius: 14px;
            background: #111827;
            color: #f9fafb;
            font-size: 13px;
            line-height: 1.65;
        }

        .attachment-list {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 10px;
        }

        .attachment-chip {
            padding: 6px 9px;
            border-radius: 999px;
            background: rgba(127, 231, 220, 0.18);
            color: inherit;
            font-size: 12px;
            font-weight: 700;
        }

        .meal-card {
            width: min(78%, 760px);
            margin: 8px 0 18px;
            padding: 18px;
            border: 1px solid var(--line);
            border-radius: var(--radius-lg);
            background: var(--surface);
            box-shadow: var(--shadow-md);
            animation: rise-in 240ms ease both;
        }

        .meal-card-title {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
        }

        .meal-card-title strong {
            color: var(--text);
            font-size: 16px;
            font-weight: 850;
            line-height: 1.25;
            letter-spacing: -0.01em;
        }

        .status-pill {
            padding: 5px 11px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 850;
            color: var(--blue);
            background: var(--blue-soft);
        }

        .status-pill.warning {
            color: var(--warning);
            background: var(--warning-bg);
        }

        .status-pill.fail {
            color: var(--danger);
            background: var(--danger-bg);
        }

        /* ── 음식 목록(주인공): 역할 뱃지 + 큰 음식명 / 작은 수치 ── */
        .food-list {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }

        .food-row {
            display: flex;
            align-items: center;
            gap: 11px;
            padding: 14px 4px;
            border-bottom: 1px solid var(--line);
            color: var(--text);
            line-height: 1.35;
        }

        .food-row:last-child {
            border-bottom: 0;
        }

        .food-name {
            flex: 1 1 auto;
            min-width: 0;
            font-size: 17px;
            font-weight: 800;
            letter-spacing: -0.01em;
            color: var(--text);
        }

        .food-figures {
            flex: 0 0 auto;
            color: var(--muted);
            font-size: 12.5px;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
        }

        .food-figures em {
            font-style: normal;
            font-size: 0.82em;
            font-weight: 700;
            color: var(--muted-2);
            margin-left: 1px;
        }

        .role-badge {
            flex: 0 0 auto;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 40px;
            padding: 5px 9px;
            border-radius: 9px;
            font-size: 12px;
            font-weight: 850;
            line-height: 1;
        }

        /* ── 영양 근거 띠(보조): 음식 아래, 총 열량 + 탄단지·나트륨 ── */
        .nutri-strip {
            display: flex;
            align-items: center;
            gap: 16px;
            margin-top: 14px;
            padding: 14px 16px;
            border-radius: var(--radius-md);
            background: var(--surface-muted);
        }

        .nutri-total {
            flex: 0 0 auto;
            display: flex;
            align-items: baseline;
            gap: 3px;
            padding-right: 16px;
            border-right: 1px solid var(--line-strong);
        }

        .nutri-total-num {
            font-size: 22px;
            font-weight: 880;
            line-height: 1;
            letter-spacing: -0.02em;
            color: var(--teal-ink);
            font-variant-numeric: tabular-nums;
        }

        .nutri-total-unit {
            font-size: 12px;
            font-weight: 800;
            color: var(--accent);
        }

        .nutri-macros {
            flex: 1 1 auto;
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 10px;
        }

        .macro-chip {
            display: flex;
            flex-direction: column;
            gap: 2px;
            min-width: 0;
        }

        .macro-label {
            color: var(--muted);
            font-size: 11px;
            font-weight: 750;
        }

        .macro-value {
            color: var(--text);
            font-size: 15px;
            font-weight: 850;
            line-height: 1.1;
            font-variant-numeric: tabular-nums;
        }

        .macro-value em {
            font-style: normal;
            font-size: 0.72em;
            font-weight: 700;
            color: var(--muted-2);
            margin-left: 1px;
        }

        .role-rice  { color: #8a6d2b; background: #fbf1d9; }
        .role-soup  { color: #2f6d8a; background: #dcf0f7; }
        .role-side  { color: #3f7a4a; background: #e0f2e4; }
        .role-bowl  { color: var(--teal-ink); background: var(--accent-soft); }
        .role-snack { color: #8a5a2f; background: #f7ead9; }
        .role-etc   { color: var(--muted); background: var(--surface-muted); }

        /* ── 경고: 카드 안 하단, 부드러운 노란 박스 ── */
        .warning-list {
            display: flex;
            align-items: flex-start;
            gap: 9px;
            margin-top: 14px;
            padding: 12px 14px;
            border-radius: var(--radius-sm);
            background: var(--warning-bg);
        }

        .warning-cap {
            flex: 0 0 auto;
            padding: 2px 8px;
            border-radius: 6px;
            background: var(--warning);
            color: #fff;
            font-size: 11px;
            font-weight: 850;
            line-height: 1.5;
        }

        .warning-list ul {
            margin: 1px 0 0;
            padding-left: 2px;
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 4px;
            color: var(--warning);
            font-size: 13px;
            font-weight: 700;
            line-height: 1.5;
        }

        /* ── 레시피 섹션 ────────────────────────────── */
        /* 카드와 같은 폭으로 정렬해 '카드에 이어지는 영역'처럼 보이게 한다. */
        [class*="st-key-recipe-wrap"] {
            width: min(78%, 760px);
        }

        .recipe-section-label {
            margin: 2px 0 6px 2px;
            color: var(--muted);
            font-size: 12px;
            font-weight: 800;
            letter-spacing: 0.02em;
        }

        /* Streamlit expander를 민트 톤 카드로 커스텀 */
        [class*="st-key-recipe-wrap"] [data-testid="stExpander"] {
            border: 1px solid var(--line);
            border-radius: var(--radius-md);
            background: var(--surface);
            box-shadow: var(--shadow-sm);
            margin-bottom: 8px;
            overflow: hidden;
        }

        [class*="st-key-recipe-wrap"] [data-testid="stExpander"] details {
            border: 0 !important;
            background: transparent !important;
        }

        [class*="st-key-recipe-wrap"] [data-testid="stExpander"] summary {
            padding: 12px 16px !important;
            font-size: 14px;
            font-weight: 750;
            color: var(--text);
            border-radius: var(--radius-md);
            transition: background 140ms ease;
        }

        [class*="st-key-recipe-wrap"] [data-testid="stExpander"] summary:hover {
            background: var(--accent-soft);
        }

        [class*="st-key-recipe-wrap"] [data-testid="stExpander"] summary svg {
            color: var(--accent);
        }

        [class*="st-key-recipe-wrap"] [data-testid="stExpanderDetails"] {
            padding: 4px 16px 16px;
        }

        /* expander 내부 전체를 하나의 흐름으로 — 블록 간 간격을 gap으로 통일 */
        .recipe-body {
            display: flex;
            flex-direction: column;
            gap: 16px;
            padding-top: 4px;
        }

        .recipe-block {
            display: flex;
            flex-direction: column;
        }

        .recipe-block-label {
            color: var(--accent);
            font-size: 12px;
            font-weight: 850;
            letter-spacing: 0.02em;
            margin-bottom: 8px;
        }

        .recipe-ingredients {
            color: var(--muted);
            font-size: 13px;
            line-height: 1.6;
        }

        /* 조리 단계 — 사진(왼쪽) + 설명(오른쪽)을 순서대로 나란히 */
        .recipe-steps {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .recipe-step {
            display: flex;
            gap: 12px;
            align-items: flex-start;
        }

        .step-figure {
            position: relative;
            flex: 0 0 auto;
            width: 128px;
            height: 88px;
            border-radius: var(--radius-sm);
            overflow: hidden;
            background: var(--surface-muted);
            border: 1px solid var(--line);
        }

        .step-photo {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }

        /* 사진 위 좌상단 단계 번호 뱃지 */
        .step-no {
            position: absolute;
            top: 6px;
            left: 6px;
            z-index: 1;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 22px;
            height: 22px;
            padding: 0 6px;
            border-radius: 999px;
            background: var(--accent);
            color: #ffffff;
            font-size: 12px;
            font-weight: 850;
            box-shadow: 0 1px 4px rgba(18, 65, 61, 0.35);
        }

        .step-text {
            flex: 1 1 auto;
            padding-top: 2px;
            color: var(--text);
            font-size: 14px;
            line-height: 1.62;
        }

        @media (max-width: 640px) {
            .step-figure {
                width: 96px;
                height: 68px;
            }
        }

        .recipe-tip {
            display: flex;
            align-items: flex-start;
            gap: 8px;
            padding: 11px 13px;
            border-radius: var(--radius-sm);
            background: var(--accent-soft);
            color: var(--teal-ink);
            font-size: 13px;
            font-weight: 650;
            line-height: 1.55;
        }

        .recipe-tip-icon {
            flex: 0 0 auto;
            line-height: 1.4;
        }

        /* 유튜브에서 보기 — 링크 버튼 */
        .recipe-youtube {
            display: inline-flex;
            align-self: flex-start;
            align-items: center;
            gap: 9px;
            padding: 10px 16px;
            border-radius: 999px;
            background: #ff0000;
            color: #ffffff !important;
            font-size: 13.5px;
            font-weight: 800;
            text-decoration: none !important;
            transition: transform 120ms ease, box-shadow 120ms ease;
            box-shadow: 0 6px 18px rgba(255, 0, 0, 0.22);
        }

        .recipe-youtube:hover {
            transform: translateY(-1px);
            box-shadow: 0 10px 24px rgba(255, 0, 0, 0.28);
        }

        .recipe-youtube-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 20px;
            height: 20px;
            border-radius: 5px;
            background: rgba(255, 255, 255, 0.22);
            font-size: 10px;
        }

        .typing-row {
            display: flex;
            justify-content: flex-start;
            margin: 16px 0;
            animation: rise-in 180ms ease both;
        }

        .typing-bubble {
            display: inline-flex;
            align-items: center;
            gap: 7px;
            padding: 16px 18px;
            border: 1px solid var(--line);
            border-radius: var(--radius-md);
            background: var(--surface);
            box-shadow: var(--shadow-sm);
        }

        /* 진행 단계 말풍선: 점 애니메이션 + 현재 단계 문구 */
        .progress-bubble {
            display: inline-flex;
            align-items: center;
            gap: 11px;
            padding: 13px 17px;
            border: 1px solid var(--user-bubble-line);
            border-radius: var(--radius-md);
            background: var(--accent-soft);
            box-shadow: var(--shadow-sm);
            animation: rise-in 180ms ease both;
        }

        .progress-dots {
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }

        .progress-text {
            color: var(--teal-ink);
            font-size: 14px;
            font-weight: 750;
            letter-spacing: -0.01em;
        }

        .typing-dot {
            width: 7px;
            height: 7px;
            border-radius: 999px;
            background: var(--accent);
            opacity: 0.35;
            animation: typing-dot 1s infinite ease-in-out;
        }

        .typing-dot:nth-child(2) {
            animation-delay: 120ms;
        }

        .typing-dot:nth-child(3) {
            animation-delay: 240ms;
        }

        @keyframes typing-dot {
            0%, 80%, 100% { transform: translateY(0); opacity: 0.35; }
            40% { transform: translateY(-4px); opacity: 1; }
        }

        @keyframes rise-in {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        @media (max-width: 760px) {
            [data-testid="stAppViewContainer"] > .main .block-container,
            .block-container {
                padding: 0 14px 118px !important;
            }

            [data-testid="stSidebar"][aria-expanded="false"] ~ [data-testid="stMain"] .block-container {
                padding-left: 0 !important;
                padding-right: 0 !important;
            }

            .top-login-link {
                top: 12px;
                right: 16px;
            }

            .st-key-conversation_shell {
                margin-top: 58px;
            }

            [data-testid="stBottom"] > div,
            [data-testid="stBottomBlockContainer"] > div,
            .stBottomBlockContainer > div {
                padding: 0 14px !important;
                margin-bottom: 18px !important;
            }

            .app-header {
                align-items: center;
                padding: 16px;
            }

            .header-meta {
                display: none;
            }

            .empty-state {
                padding-top: 34px;
            }

            .empty-state h1 {
                font-size: 29px;
            }

            .message-stack,
            .message-row.user .message-stack,
            .meal-card {
                width: 100%;
            }

            .message-bubble {
                font-size: 14px;
            }

            .nutri-strip {
                flex-direction: column;
                align-items: stretch;
                gap: 12px;
            }

            .nutri-total {
                padding-right: 0;
                padding-bottom: 10px;
                border-right: 0;
                border-bottom: 1px solid var(--line-strong);
            }

            .food-name {
                font-size: 16px;
            }
        }
        </style>
        """,
    )
