import streamlit as st
import os

if "AWS_ACCESS_KEY_ID" in st.secrets:
    os.environ["AWS_ACCESS_KEY_ID"] = st.secrets["AWS_ACCESS_KEY_ID"]
    os.environ["AWS_SECRET_ACCESS_KEY"] = st.secrets["AWS_SECRET_ACCESS_KEY"]
    os.environ["AWS_DEFAULT_REGION"] = st.secrets.get("AWS_DEFAULT_REGION", "us-east-1")

from rag_engine import RAGEngine

KB_ID = st.secrets.get("BEDROCK_KB_ID", "ENBRB90GYL")

def check_password():
    """Returns `True` if the user had the correct password."""
    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.error("Password is incorrect.")
        return False
    else:
        return True

BASE_URL = "https://www.sos.ms.gov/adminsearch/ACCode/"

def format_answer_inline(answer: str, refs: list[dict]) -> str:
    
    answer = (answer or "").rstrip()
    if not refs:
        return answer

    unique_refs = []
    seen = set()
    for r in refs:
        if isinstance(r, str):
            key = r
        else:
            key = (r.get("filename"), r.get("law"))
        
        if key not in seen:
            seen.add(key)
            unique_refs.append(r)

    footnote_markers = "".join([f"[{i+1}]" for i in range(len(unique_refs))])
    
    if answer[-1] not in ".!?":
        answer += "."
    
    formatted_text = f"{answer} {footnote_markers}"


    sources_text = "\n\n---\n**Sources:**\n"
    
    for i, r in enumerate(unique_refs):
        index = i + 1
        
        if isinstance(r, str):
            link = f"[{r}]({BASE_URL}{r})"
            sources_text += f"{index}. {link}\n"
            continue

        fn = r.get("filename") or "unknown"
        link = f"[{fn}]({BASE_URL}{fn})"
        
        meta_parts = []
        if r.get("title"):  meta_parts.append(f"**{r['title']}**")
        if r.get("agency"): meta_parts.append(f"{r['agency']}")
        
        meta_str = " | ".join(meta_parts)
        
        if meta_str:
            sources_text += f"{index}. {link} — {meta_str}\n"
        else:
            sources_text += f"{index}. {link}\n"

    return formatted_text + sources_text

def main():
    st.set_page_config(page_title="MS Regulations", layout="wide")

    if not check_password():
        st.stop()  # Stop here if password is wrong

    # Main app
    st.title("Mississippi SoS Assistant")

    if "engine" not in st.session_state:
        st.session_state.engine = RAGEngine(kb_id=KB_ID)

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    if prompt := st.chat_input("Ask a question about MS regulations..."):
        st.chat_message("user").markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("assistant"):
            with st.spinner("Searching regulations..."):
                answer, refs = st.session_state.engine.query(prompt)
                formatted = format_answer_inline(answer, refs)
                st.markdown(formatted)

        st.session_state.messages.append({"role": "assistant", "content": formatted})

if __name__ == "__main__":
    main()