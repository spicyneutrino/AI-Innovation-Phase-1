import streamlit as st
import os
from dotenv import load_dotenv
from rag_engine import RAGEngine

load_dotenv()

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

def format_answer_with_sources(answer: str, sources: list[str]) -> str:
    """
    Format as: Answer. {[filename.pdf](url)}
    """

    answer = (answer or "").strip()
    
    if not sources:
        return answer

    base_url = "https://www.sos.ms.gov/adminsearch/ACCode/"

    formatted_sources = [f"[{s}]({base_url}{s})" for s in sorted(set(sources))]

    src_str = ", ".join(formatted_sources)

    if answer and answer[-1] in ".!?":
        return f"{answer} {{{src_str}}}"

    return f"{answer}. {{{src_str}}}"


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

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("Ask a question about MS regulations..."):
        st.chat_message("user").markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("assistant"):
            with st.spinner("Searching regulations..."):
                answer, sources = st.session_state.engine.query(prompt)
                formatted = format_answer_with_sources(answer, sources)
                st.markdown(formatted)

        st.session_state.messages.append({"role": "assistant", "content": formatted})


if __name__ == "__main__":
    main()