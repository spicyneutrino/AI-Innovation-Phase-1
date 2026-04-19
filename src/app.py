import html
import os
import re
import uuid
from pathlib import Path

import streamlit as st

if "AWS_ACCESS_KEY_ID" in st.secrets:
    os.environ["AWS_ACCESS_KEY_ID"] = st.secrets["AWS_ACCESS_KEY_ID"]
    os.environ["AWS_SECRET_ACCESS_KEY"] = st.secrets["AWS_SECRET_ACCESS_KEY"]
    os.environ["AWS_DEFAULT_REGION"] = st.secrets.get("AWS_DEFAULT_REGION", "us-east-1")

from rag_engine import RAGEngine

KB_ID = st.secrets.get("BEDROCK_KB_ID", "ENBRB90GYL")
MS_BASE_URL = "https://www.sos.ms.gov/adminsearch/ACCode/"

_STUB_STATES = {"GA", "LA", "TN"}

SUGGESTED_QUESTIONS = [
    {"category": "Infrastructure", "q": "To allow a department to perform a technical review, request change order approvals must contain?"},
    {"category": "Agencies",       "q": "What is the MJIC Unit responsible for?"},
    {"category": "Agriculture",    "q": "What permit shall be required by any person or entity owning exotic livestock?"},
    {"category": "Finance",        "q": "What is the filing application fee for a Loan Production Office?"},
]

# Optional bundled seal (same directory as this file or src/static/). PNGs are
# gitignored by default; add an exception in .gitignore if you commit an asset.
_LOGO_PATHS = (
    Path(__file__).resolve().parent / "ms_sos_logo.png",
    Path(__file__).resolve().parent / "static" / "ms_sos_logo.png",
)


def _show_logo(width: int = 88) -> None:
    """Streamlit-safe logo: local file if present, else a styled fallback (no broken <img>)."""
    for path in _LOGO_PATHS:
        if path.is_file():
            st.image(str(path), width=width)
            return
    side = max(56, min(width, 120))
    st.markdown(
        f'<div style="display:flex;justify-content:center;margin:0 0 10px 0;">'
        f'<div style="width:{side}px;height:{side}px;border-radius:50%;'
        "background:linear-gradient(160deg,#1e2d4a,#0d1528);border:2px solid #5b8fff;"
        f'display:flex;align-items:center;justify-content:center;font-size:{side // 3}px;">'
        "⚖️</div></div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Design system CSS
# ---------------------------------------------------------------------------

_CSS = """
<style>
/* ── Fonts ─────────────────────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"], .stMarkdown, .stText {
    font-family: 'Inter', sans-serif !important;
}

/* ── Page ───────────────────────────────────────────────────────────────── */
.stApp { background-color: #0b1326; }

.main .block-container {
    max-width: 960px !important;
    padding-top: 28px !important;
    padding-left: 40px !important;
    padding-right: 40px !important;
    padding-bottom: 16px !important;
}

/* ── Sidebar ────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #0b1326 !important;
    border-right: 1px solid #1e2d4a !important;
    min-width: 240px !important;
    max-width: 240px !important;
}
[data-testid="stSidebar"] .block-container {
    padding-top: 20px;
    padding-left: 12px;
    padding-right: 12px;
}
[data-testid="stSidebar"] hr {
    border-color: #1e2d4a !important;
    margin: 10px 0 !important;
}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stMarkdown p {
    color: #e8eeff !important;
    font-size: 13px !important;
}

/* Active chat item (rendered as div, not button) */
.active-chat-item {
    display: flex;
    align-items: center;
    gap: 8px;
    background-color: rgba(91, 143, 255, 0.1);
    border-left: 2px solid #5b8fff;
    border-radius: 6px;
    padding: 8px 10px;
    color: #5b8fff;
    font-size: 13px;
    font-weight: 500;
    margin: 2px 0;
    line-height: 1.4;
    word-break: break-word;
}
.active-chat-dot {
    color: #5b8fff;
    font-size: 8px;
    flex-shrink: 0;
    margin-top: 1px;
}
.active-chat-meta {
    font-size: 11px;
    color: #5b8fff;
    opacity: 0.7;
    font-weight: 400;
}

/* ── Buttons ────────────────────────────────────────────────────────────── */
.stButton > button {
    background-color: #111c35 !important;
    color: #e8eeff !important;
    border: 1px solid #1e2d4a !important;
    border-radius: 8px !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    height: 36px;
    transition: background-color 0.15s ease, border-color 0.15s ease !important;
}
.stButton > button:hover {
    background-color: #1e2d4a !important;
    border-color: #5b8fff !important;
    color: #e8eeff !important;
}
.stButton > button[kind="primary"],
button[data-testid="baseButton-primary"] {
    background-color: #5b8fff !important;
    border-color: #5b8fff !important;
    color: #0b1326 !important;
    font-weight: 600 !important;
}
.stButton > button[kind="primary"]:hover {
    background-color: #7aa3ff !important;
    border-color: #7aa3ff !important;
}

/* ── Inputs ─────────────────────────────────────────────────────────────── */
[data-testid="stTextInput"] input,
[data-testid="stTextInputRootElement"] input {
    background-color: #111c35 !important;
    border: 1px solid #1e2d4a !important;
    border-radius: 8px !important;
    color: #e8eeff !important;
    font-size: 14px !important;
    font-family: 'Inter', sans-serif !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextInputRootElement"] input:focus {
    border-color: #5b8fff !important;
    box-shadow: 0 0 0 2px rgba(91, 143, 255, 0.2) !important;
}
[data-testid="stTextInput"] input::placeholder { color: #94a3b8 !important; }

/* ── Chat input ─────────────────────────────────────────────────────────── */
[data-testid="stChatInputContainer"] {
    background-color: #0b1326 !important;
    border-top: 1px solid #1e2d4a !important;
    padding: 12px 0 !important;
}
[data-testid="stChatInputContainer"] textarea {
    background-color: #151d36 !important;
    border: 1px solid #2a3f66 !important;
    border-radius: 8px !important;
    color: #e8eeff !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 14px !important;
}
[data-testid="stChatInputContainer"] textarea:focus {
    border-color: #5b8fff !important;
    box-shadow: 0 0 0 2px rgba(91, 143, 255, 0.2) !important;
}
[data-testid="stChatInputContainer"] textarea::placeholder { color: #94a3b8 !important; }

/* ── Chat messages ───────────────────────────────────────────────────────── */
[data-testid="stChatMessage"] {
    background-color: transparent !important;
    border: none !important;
    padding: 8px 0 !important;
}
/* User — right-aligned bubble */
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
    flex-direction: row-reverse !important;
}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] {
    background-color: #111c35 !important;
    border: 1px solid #1e2d4a !important;
    border-radius: 8px !important;
    padding: 10px 14px !important;
    margin-left: auto !important;
    max-width: 78% !important;
}
/* Assistant — full width, transparent */
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) [data-testid="stChatMessageContent"] {
    background-color: transparent !important;
    max-width: 100% !important;
}
/* Avatars */
[data-testid="chatAvatarIcon-user"],
[data-testid="chatAvatarIcon-assistant"] {
    background-color: #111c35 !important;
    border: 1px solid #1e2d4a !important;
    border-radius: 50% !important;
    color: #e8eeff !important;
}

/* ── Footnote markers ────────────────────────────────────────────────────── */
sup.fn-ref {
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    color: #5b8fff;
    background-color: rgba(91, 143, 255, 0.12);
    border: 1px solid rgba(91, 143, 255, 0.3);
    border-radius: 3px;
    padding: 1px 4px;
    vertical-align: super;
    margin-left: 2px;
    cursor: default;
    white-space: nowrap;
    line-height: 1;
}

/* ── Expanders (citations) ───────────────────────────────────────────────── */
[data-testid="stExpander"] {
    background-color: #111c35 !important;
    border: 1px solid #1e2d4a !important;
    border-radius: 8px !important;
    margin-bottom: 6px !important;
    overflow: hidden;
}
[data-testid="stExpander"] summary,
.streamlit-expanderHeader {
    background-color: #111c35 !important;
    color: #e8eeff !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 12px !important;
    padding: 10px 14px !important;
    border-radius: 8px !important;
}
[data-testid="stExpander"] summary:hover,
.streamlit-expanderHeader:hover { background-color: #1e2d4a !important; }
[data-testid="stExpander"] > div:last-child,
.streamlit-expanderContent {
    background-color: #0d1830 !important;
    border-top: 1px solid #1e2d4a !important;
    border-left: 2px solid #5b8fff !important;
    padding: 14px 16px !important;
}

/* ── Dividers ───────────────────────────────────────────────────────────── */
hr { border-color: #1e2d4a !important; margin: 12px 0 !important; }

/* ── Typography ─────────────────────────────────────────────────────────── */
h1 { font-size: 22px !important; font-weight: 600 !important; color: #e8eeff !important; line-height: 1.2 !important; }
h2 { font-size: 20px !important; font-weight: 600 !important; color: #e8eeff !important; line-height: 1.2 !important; }
h3 { font-size: 15px !important; font-weight: 600 !important; color: #e8eeff !important; line-height: 1.2 !important; }

/* ── Inline code / citations ────────────────────────────────────────────── */
code {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 12px !important;
    background-color: #111c35 !important;
    border: 1px solid #1e2d4a !important;
    border-radius: 4px !important;
    padding: 1px 5px !important;
    color: #5b8fff !important;
}

/* ── State badges ────────────────────────────────────────────────────────── */
.sos-badge {
    display: inline-block;
    background-color: #1e2d4a;
    color: #e8eeff;
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    border-radius: 4px;
    padding: 2px 7px;
    margin-right: 6px;
    vertical-align: middle;
}
.sos-badge-primary { background-color: #5b8fff; color: #0b1326; }
.sos-badge-warning { background-color: transparent; border: 1px solid #fbbf24; color: #fbbf24; }

/* ── Context mode badge ─────────────────────────────────────────────────── */
.ctx-badge {
    display: inline-block;
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.04em;
    border-radius: 4px;
    padding: 2px 8px;
    vertical-align: middle;
    margin-left: 10px;
}
.ctx-on  { background-color: rgba(91, 143, 255, 0.12); color: #5b8fff; border: 1px solid rgba(91,143,255,0.3); }
.ctx-off { background-color: rgba(148, 163, 184, 0.1); color: #94a3b8; border: 1px solid rgba(148,163,184,0.2); }

/* ── Citation meta rows ─────────────────────────────────────────────────── */
.sos-meta-row {
    display: flex;
    gap: 8px;
    align-items: baseline;
    margin-bottom: 5px;
    font-size: 13px;
    line-height: 1.5;
}
.sos-meta-key {
    font-weight: 500;
    color: #94a3b8;
    min-width: 90px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    flex-shrink: 0;
}
.sos-meta-val { color: #e8eeff; word-break: break-all; }
.sos-meta-val a { color: #5b8fff !important; text-decoration: none !important; }
.sos-meta-val a:hover { text-decoration: underline !important; }
.sos-cit-id { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #5b8fff; }

/* ── Micro labels (section headers) ─────────────────────────────────────── */
.sos-label {
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: #94a3b8;
    margin: 0 0 8px 0;
}

/* ── Welcome / empty state ───────────────────────────────────────────────── */
.welcome-hero {
    text-align: center;
    padding: 48px 0 32px 0;
}
.welcome-hero h2 {
    font-size: 26px !important;
    font-weight: 600 !important;
    color: #e8eeff !important;
    margin: 0 0 8px 0 !important;
}
.welcome-hero p {
    color: #94a3b8;
    font-size: 15px;
    margin: 0;
}

/* Suggested question cards */
.suggest-card-category {
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: #5b8fff;
    margin-bottom: 5px;
}
.suggest-card-q {
    font-size: 13px;
    color: #e8eeff;
    line-height: 1.5;
}
div[data-testid^="column"] .stButton > button {
    text-align: left !important;
    white-space: pre-line !important;
    height: auto !important;
    min-height: 88px !important;
    padding: 14px 16px !important;
    line-height: 1.45 !important;
    font-size: 13px !important;
}

/* ── Link buttons ────────────────────────────────────────────────────────── */
[data-testid="stLinkButton"] a {
    background-color: #111c35 !important;
    border: 1px solid #5b8fff !important;
    color: #5b8fff !important;
    border-radius: 8px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    text-decoration: none !important;
    padding: 6px 14px !important;
    display: inline-block !important;
}
[data-testid="stLinkButton"] a:hover {
    background-color: #5b8fff !important;
    color: #0b1326 !important;
}

/* ── Checkbox ───────────────────────────────────────────────────────────── */
[data-testid="stCheckbox"] label { color: #e8eeff !important; font-size: 13px !important; }

/* ── Text area (doc preview) ─────────────────────────────────────────────── */
[data-testid="stTextArea"] textarea {
    background-color: #0b1326 !important;
    border: 1px solid #1e2d4a !important;
    border-radius: 6px !important;
    color: #94a3b8 !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 12px !important;
    line-height: 1.6 !important;
}

/* ── Password gate ───────────────────────────────────────────────────────── */
.login-wrap {
    text-align: center;
}
.login-wrap h2 {
    font-size: 20px !important;
    font-weight: 600 !important;
    color: #e8eeff !important;
    margin: 0 0 6px 0 !important;
}
.login-wrap p {
    color: #94a3b8;
    font-size: 14px;
    margin: 0 0 20px 0;
}

/* ── Scrollbar ───────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: #0b1326; }
::-webkit-scrollbar-thumb { background: #1e2d4a; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #5b8fff; }

/* ── Spinner ─────────────────────────────────────────────────────────────── */
[data-testid="stSpinner"] { color: #5b8fff !important; }
</style>
"""


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def check_password() -> bool:
    def password_entered():
        if st.session_state.get("password") == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    def _login_panel(show_error: bool) -> None:
        _, col, _ = st.columns([1, 1.2, 1])
        with col:
            st.markdown('<div style="margin-top:40px;"></div>', unsafe_allow_html=True)
            _show_logo(80)
            st.markdown(
                '<div class="login-wrap">'
                "<h2>SoS Regulation Assistant</h2>"
                "<p>Mississippi Secretary of State · Regulatory Intelligence</p>"
                "</div>",
                unsafe_allow_html=True,
            )
            st.text_input(
                "Password",
                type="password",
                on_change=password_entered,
                key="password",
                autocomplete="current-password",
            )
            if show_error:
                st.error("Incorrect password.")

    if "password_correct" not in st.session_state:
        _login_panel(False)
        return False
    if not st.session_state["password_correct"]:
        _login_panel(True)
        return False
    return True


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

def _new_chat(name: str | None = None) -> str:
    chat_id = str(uuid.uuid4())
    n = len(st.session_state.chats) + 1
    st.session_state.chats[chat_id] = {
        "name": name or f"Chat {n}",
        "messages": [],
        "session_id": None,
        "contextual": True,
    }
    return chat_id


def init_session_state():
    if "engine" not in st.session_state:
        st.session_state.engine = RAGEngine(kb_id=KB_ID)
    if "chats" not in st.session_state:
        st.session_state.chats = {}
    if not st.session_state.chats:
        st.session_state.active = _new_chat("Chat 1")
    if "active" not in st.session_state or st.session_state.active not in st.session_state.chats:
        st.session_state.active = next(iter(st.session_state.chats))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state_badge(state_code: str) -> str:
    if not state_code:
        return ""
    code = (state_code or "").strip().upper()[:8]
    label = html.escape(code)
    if code == "MS":
        cls = "sos-badge sos-badge-primary"
    elif code in _STUB_STATES:
        cls = "sos-badge sos-badge-warning"
    else:
        cls = "sos-badge"
    return f'<span class="{cls}">{label}</span>'


def _styled_answer(answer: str, ref_count: int) -> str:
    """Append styled superscript footnote markers and return HTML."""
    answer = html.escape((answer or "").rstrip())
    if not ref_count:
        return answer
    if answer and answer[-1] not in ".!?":
        answer += "."
    markers = "".join(
        f'<sup class="fn-ref">[{i}]</sup>'
        for i in range(1, ref_count + 1)
    )
    return f"{answer}&ensp;{markers}"


def _citation_row(key: str, val: str, is_link: bool = False):
    """Render a single metadata row inside a citation expander."""
    if not val:
        return
    val_esc = html.escape(val, quote=True)
    if is_link:
        val_html = f'<a href="{val_esc}" target="_blank" rel="noopener noreferrer">{val_esc}</a>'
    else:
        val_html = val_esc
    st.markdown(
        f'<div class="sos-meta-row">'
        f'<span class="sos-meta-key">{key}</span>'
        f'<span class="sos-meta-val">{val_html}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Citation rendering
# ---------------------------------------------------------------------------

def render_citations(refs: list[dict], engine: RAGEngine):
    if not refs:
        return
    st.markdown('<div class="sos-label" style="margin-top:14px;">Sources</div>', unsafe_allow_html=True)
    for i, r in enumerate(refs, 1):
        fn = r.get("filename") or "unknown"
        agency = r.get("agency") or ""
        state_code = (r.get("state") or "").upper()

        expander_label = f"[{i}]  {fn}" + (f"  —  {agency}" if agency else "")
        with st.expander(expander_label):
            # Badge + filename header
            badge_html = _state_badge(state_code)
            fn_safe = html.escape(fn)
            st.markdown(
                f'<div style="margin-bottom:12px;">'
                f'{badge_html}<span class="sos-cit-id">{fn_safe}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            _citation_row("State",    state_code)
            _citation_row("Agency",   r.get("agency", ""))
            _citation_row("Title",    r.get("title", ""))
            _citation_row("Law/Rule", r.get("law", ""))
            _citation_row("Source",   r.get("source_url", ""), is_link=bool(r.get("source_url")))
            _citation_row("File",     fn)

            # Action: S3 presigned URL or MS fallback link
            s3_uri = r.get("s3_uri")
            if s3_uri:
                url = engine.get_presigned_url(s3_uri)
                if url:
                    st.link_button("⬇  Download / View file", url)
            elif state_code == "MS" and fn and fn != "unknown":
                st.link_button("↗  View on sos.ms.gov", f"{MS_BASE_URL}{fn}")

            # Text preview for .txt documents
            if s3_uri and fn.lower().endswith(".txt"):
                with st.spinner("Loading preview…"):
                    text = engine.get_document_text(s3_uri)
                if text:
                    st.markdown(
                        '<div class="sos-label" style="margin-top:12px;">Preview</div>',
                        unsafe_allow_html=True,
                    )
                    st.text_area(
                        label="preview",
                        value=text,
                        height=280,
                        disabled=True,
                        label_visibility="collapsed",
                        key=f"preview_{i}_{fn}",
                    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar():
    with st.sidebar:
        _show_logo(96)
        st.markdown(
            '<p style="font-size:14px;font-weight:600;color:#e8eeff;margin:6px 0 0 0;">'
            "SoS Regulation Assistant</p>"
            '<p style="font-size:11px;color:#94a3b8;margin:2px 0 0 0;">Mississippi · Regulatory Intelligence</p>',
            unsafe_allow_html=True,
        )
        st.divider()

        if st.button("＋  New Chat", use_container_width=True, key="new_chat_btn"):
            st.session_state.active = _new_chat()
            st.rerun()

        st.markdown('<div class="sos-label" style="margin:12px 0 6px 0;">Conversations</div>', unsafe_allow_html=True)

        for chat_id, chat in list(st.session_state.chats.items()):
            is_active = chat_id == st.session_state.active
            msg_count = sum(1 for m in chat["messages"] if m["role"] == "user")
            count_str = f"{msg_count} msg{'s' if msg_count != 1 else ''}" if msg_count else "new"

            col_name, col_del = st.columns([5, 1])
            with col_name:
                if is_active:
                    st.markdown(
                        f'<div class="active-chat-item">'
                        f'<span class="active-chat-dot">●</span>'
                        f'<span>{chat["name"]}<br>'
                        f'<span class="active-chat-meta">{count_str}</span></span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    label = f"{chat['name']}\n{count_str}"
                    if st.button(label, key=f"chat_btn_{chat_id}", use_container_width=True):
                        st.session_state.active = chat_id
                        st.rerun()
            with col_del:
                if st.button("✕", key=f"del_{chat_id}", help="Delete chat"):
                    del st.session_state.chats[chat_id]
                    if st.session_state.active == chat_id:
                        st.session_state.active = (
                            next(iter(st.session_state.chats))
                            if st.session_state.chats
                            else _new_chat()
                        )
                    st.rerun()

        st.divider()

        active_chat = st.session_state.chats[st.session_state.active]
        st.markdown('<div class="sos-label">Chat settings</div>', unsafe_allow_html=True)

        new_name = st.text_input(
            "Name",
            value=active_chat["name"],
            key=f"name_input_{st.session_state.active}",
        )
        if new_name and new_name != active_chat["name"]:
            active_chat["name"] = new_name
            st.rerun()

        active_chat["contextual"] = st.checkbox(
            "Contextual mode",
            value=active_chat["contextual"],
            key=f"ctx_{st.session_state.active}",
            help="When on, Bedrock remembers previous turns in this chat.",
        )

        if st.button("🗑  Clear messages", use_container_width=True, key="clear_btn"):
            active_chat["messages"] = []
            active_chat["session_id"] = None
            st.rerun()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="SoS Regulation Assistant",
        page_icon="⚖️",
        layout="wide",
    )
    st.markdown(_CSS, unsafe_allow_html=True)

    if not check_password():
        st.stop()

    init_session_state()
    render_sidebar()

    active_chat = st.session_state.chats[st.session_state.active]
    engine: RAGEngine = st.session_state.engine

    # ── Header ──────────────────────────────────────────────────────────── #
    ctx_cls = "ctx-on" if active_chat["contextual"] else "ctx-off"
    ctx_label = "Contextual" if active_chat["contextual"] else "Standalone"
    st.markdown(
        f'<h1 style="margin:0 0 4px 0;padding:0;">'
        f'{active_chat["name"]}'
        f'<span class="ctx-badge {ctx_cls}">{ctx_label}</span>'
        f'</h1>'
        f'<p style="margin:0;color:#94a3b8;font-size:13px;">'
        f'Mississippi Secretary of State · Regulatory Intelligence'
        f'</p>',
        unsafe_allow_html=True,
    )
    st.divider()

    # ── Welcome / empty state ─────────────────────────────────────────────── #
    if not active_chat["messages"]:
        st.markdown(
            '<div class="welcome-hero">'
            '<h2>What would you like to know?</h2>'
            '<p>Search across Mississippi Secretary of State regulatory rules and agency codes.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        cols = st.columns(2)
        for idx, item in enumerate(SUGGESTED_QUESTIONS):
            with cols[idx % 2]:
                label = f"{item['category'].upper()}\n{item['q']}"
                if st.button(label, key=f"suggested_{idx}", use_container_width=True):
                    st.session_state.selected_question = item["q"]
                    st.rerun()

    # ── Handle suggested question ────────────────────────────────────────── #
    if "selected_question" in st.session_state:
        prompt = st.session_state.pop("selected_question")
        _process_prompt(prompt, active_chat, engine)
        st.rerun()

    # ── Render conversation ──────────────────────────────────────────────── #
    for msg in active_chat["messages"]:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                # Re-render styled footnotes from plain stored text
                plain = msg["content"]
                ref_count = len(msg.get("refs") or [])
                # Strip trailing plain markers before re-rendering styled ones
                clean = re.sub(r'(\s*\[[\d\s\[\]]+\]\s*)+$', '', plain).rstrip()
                styled = _styled_answer(clean, ref_count)
                st.markdown(styled, unsafe_allow_html=True)
                render_citations(msg.get("refs") or [], engine)
            else:
                st.markdown(msg["content"])

    # ── Chat input ───────────────────────────────────────────────────────── #
    if prompt := st.chat_input("Ask about state regulations…"):
        _process_prompt(prompt, active_chat, engine)


def _process_prompt(prompt: str, active_chat: dict, engine: RAGEngine):
    with st.chat_message("user"):
        st.markdown(prompt)
    active_chat["messages"].append({"role": "user", "content": prompt})

    session_id = active_chat["session_id"] if active_chat["contextual"] else None

    with st.chat_message("assistant"):
        with st.spinner("Searching regulations…"):
            answer, refs, new_session_id = engine.query(prompt, session_id=session_id)

        if active_chat["contextual"] and new_session_id:
            active_chat["session_id"] = new_session_id

        answer = (answer or "").rstrip()
        styled = _styled_answer(answer, len(refs))
        st.markdown(styled, unsafe_allow_html=True)
        render_citations(refs, engine)

    # Store plain answer text + refs (styled markers re-generated on re-render)
    active_chat["messages"].append({"role": "assistant", "content": answer, "refs": refs})


if __name__ == "__main__":
    main()
