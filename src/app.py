import base64
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

STATE_SCOPE_OPTIONS = ["MS", "LA", "TN", "AR", "GA", "TX", "AL"]

SUGGESTED_QUESTIONS = [
    {
        "category": "Dental", 
        "q": "Can a dental assistant monitor a patient under nitrous oxide in Mississippi?"
    },
    {
        "category": "Real Estate", 
        "q": "What are the continuing education hour requirements for a real estate broker in Louisiana?"
    },
    {
        "category": "Medical", 
        "q": "What are the biennial renewal and expiration date rules for a medical license in Georgia?"
    },
    {
        "category": "Comparison", 
        "q": "Compare the real estate broker renewal hours between Louisiana and Mississippi."
    }
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


def _sidebar_brand_html(width: int = 96) -> str:
    """Single centered block: seal image + title + subtitle (for sidebar only)."""
    img_html = ""
    for path in _LOGO_PATHS:
        if path.is_file():
            b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            ext = path.suffix.lower().lstrip(".") or "png"
            mime = "image/png" if ext == "png" else "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
            img_html = (
                f'<img src="data:{mime};base64,{b64}" width="{width}" alt="" '
                'style="display:block;margin:0 auto 10px auto;" />'
            )
            break
    if not img_html:
        side = max(56, min(width, 120))
        img_html = (
            f'<div style="width:{side}px;height:{side}px;border-radius:50%;margin:0 auto 10px auto;'
            "background:linear-gradient(160deg,#1e2d4a,#0d1528);border:2px solid #5b8fff;"
            f'display:flex;align-items:center;justify-content:center;font-size:{side // 3}px;">⚖️</div>'
        )
    return (
        '<div class="sos-sidebar-brand" style="text-align:center;">'
        f"{img_html}"
        '<h3 style="margin:0 0 4px 0;">SoS Regulation Assistant</h3>'
        '<p style="margin:0;opacity:0.92;font-size:0.9em;">Multi-State Regulatory Intelligence</p>'
        "</div>"
    )


# ---------------------------------------------------------------------------
# Design system CSS
# ---------------------------------------------------------------------------

def load_css():
    """Reads the external CSS file and injects it into Streamlit."""
    css_path = Path(__file__).resolve().parent / "style.css"
    if css_path.is_file():
        with open(css_path, "r") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def check_password() -> bool:
    def _check_password():
        if st.session_state.get("password_input") == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password_input"]
        else:
            st.session_state["password_correct"] = False

    def _login_panel(show_error: bool) -> None:
        # Use a narrower center column for a tighter login feel
        _, col, _ = st.columns([1, 1.5, 1])

        with col:
            # Spacer for top margin
            st.markdown('<div style="margin-top:80px;"></div>', unsafe_allow_html=True)

            logo_url = ""
            for path in _LOGO_PATHS:
                if path.is_file():
                    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
                    ext = path.suffix.lower().lstrip(".") or "png"
                    mime = (
                        "image/png"
                        if ext == "png"
                        else "image/jpeg"
                        if ext in ("jpg", "jpeg")
                        else f"image/{ext}"
                    )
                    logo_url = f"data:{mime};base64,{b64}"
                    break

            logo_html = (
                f'<img src="{logo_url}" width="100" style="margin-bottom: 20px;" alt="">'
                if logo_url
                else '<div style="width:100px;height:100px;border-radius:50%;margin:0 auto 20px auto;'
                "background:linear-gradient(160deg,#1e2d4a,#0d1528);border:2px solid #5b8fff;"
                'display:flex;align-items:center;justify-content:center;font-size:34px;">⚖️</div>'
            )

            # Center the logo, title, and subtitle using a single markdown block
            st.markdown(
                f"""
                <div class="login-hero" style="text-align: center;">
                    {logo_html}
                    <h2 style="margin-bottom: 0;">SoS Regulation Assistant</h2>
                    <p style="color: #94a3b8; margin-bottom: 30px;">Multi-State Regulatory Intelligence</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.text_input(
                "Password",
                type="password",
                key="password_input",
                on_change=_check_password,
                autocomplete="current-password",
            )

            if show_error:
                st.markdown(
                    '<p style="color: #ff4b4b; text-align: center; font-size: 14px; margin-top: 10px;">'
                    "Invalid password.</p>",
                    unsafe_allow_html=True,
                )

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

def render_citations(refs: list[dict], engine: RAGEngine, *, key_ns: str):
    """key_ns must be unique per assistant message (e.g. message index) so preview widgets never collide."""
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
                    st.link_button(
                        "⬇  Download / View file",
                        url,
                        key=f"dl_{key_ns}_{i}",
                    )
            elif state_code == "MS" and fn and fn != "unknown":
                st.link_button(
                    "↗  View on sos.ms.gov",
                    f"{MS_BASE_URL}{fn}",
                    key=f"ms_{key_ns}_{i}",
                )

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
                        key=f"preview_{key_ns}_{i}",
                    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar():
    with st.sidebar:
        st.markdown(_sidebar_brand_html(96), unsafe_allow_html=True)
        st.divider()

        if st.button("＋  New Chat", use_container_width=True, key="new_chat_btn"):
            st.session_state.active = _new_chat()
            st.rerun()

        st.markdown('<div class="sos-label" style="margin:12px 0 6px 0;">Conversations</div>', unsafe_allow_html=True)

        for chat_id, chat in list(st.session_state.chats.items()):
            is_active = chat_id == st.session_state.active
            msg_count = sum(1 for m in chat["messages"] if m["role"] == "user")
            count_str = f"{msg_count} msg{'s' if msg_count != 1 else ''}" if msg_count else "new"

            col_name, col_del = st.columns([11, 4])
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
                if st.button("✕", key=f"del_{chat_id}", help="Delete chat", use_container_width=True):
                    del st.session_state.chats[chat_id]
                    if st.session_state.active == chat_id:
                        st.session_state.active = (
                            next(iter(st.session_state.chats))
                            if st.session_state.chats
                            else _new_chat()
                        )
                    st.rerun()

        st.markdown('<div class="sos-label" style="margin:12px 0 6px 0;">Scope</div>', unsafe_allow_html=True)
        st.multiselect(
            "State Filter",
            options=STATE_SCOPE_OPTIONS,
            default=STATE_SCOPE_OPTIONS,
            key="target_states",
            help="All states are selected by default. Remove states to narrow the search, or clear the selection to search the full knowledge base without a state filter.",
        )
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
        page_icon="📜",
        layout="wide",
    )
    load_css()

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
        f'<p style="margin:0;color:#e8eeff;font-size:13px;">'
        f'Multi-State Regulatory Intelligence'
        f'</p>',
        unsafe_allow_html=True,
    )
    st.divider()

    # ── Welcome / empty state ─────────────────────────────────────────────── #
    if not active_chat["messages"]:
        st.markdown(
            '<div class="welcome-hero">'
            '<h2>What would you like to know?</h2>'
            '<p>Search across Mississippi, Alabama, Louisiana, Georgia, Tennessee, Arkansas, and Texas for '
            'regulations related to the Board of Medical Licensure, Mississippi Real Estate Commission, '
            'and Board of Dental Examiners.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        cols = st.columns(2)
        for idx, item in enumerate(SUGGESTED_QUESTIONS):
            with cols[idx % 2]:
                label = item["q"]
                if st.button(label, key=f"suggested_{idx}", use_container_width=True):
                    st.session_state.selected_question = item["q"]
                    st.rerun()

    # ── Handle suggested question ────────────────────────────────────────── #
    if "selected_question" in st.session_state:
        prompt = st.session_state.pop("selected_question")
        _process_prompt(prompt, active_chat, engine)
        st.rerun()

    # ── Render conversation ──────────────────────────────────────────────── #
    for msg_idx, msg in enumerate(active_chat["messages"]):
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                # Re-render styled footnotes from plain stored text
                plain = msg["content"]
                ref_count = len(msg.get("refs") or [])
                # Strip trailing plain markers before re-rendering styled ones
                clean = re.sub(r'(\s*\[[\d\s\[\]]+\]\s*)+$', '', plain).rstrip()
                styled = _styled_answer(clean, ref_count)
                st.markdown(styled, unsafe_allow_html=True)
                render_citations(msg.get("refs") or [], engine, key_ns=str(msg_idx))
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
            scope = list(st.session_state.get("target_states") or [])
            answer, refs, new_session_id = engine.query(
                prompt,
                session_id=session_id,
                target_states=scope,
            )

        if active_chat["contextual"] and new_session_id:
            active_chat["session_id"] = new_session_id

        answer = (answer or "").rstrip()
        styled = _styled_answer(answer, len(refs))
        st.markdown(styled, unsafe_allow_html=True)
        # Same slot the assistant row will occupy after append (unique widget keys).
        render_citations(refs, engine, key_ns=str(len(active_chat["messages"])))

    # Store plain answer text + refs (styled markers re-generated on re-render)
    active_chat["messages"].append({"role": "assistant", "content": answer, "refs": refs})


if __name__ == "__main__":
    main()
