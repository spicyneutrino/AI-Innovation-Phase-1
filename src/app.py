import streamlit as st
from rag_engine import RAGEngine

KB_ID = "ENBRB90GYL"

def format_answer_inline(answer: str, refs: list[dict]) -> str:
    answer = (answer or "").rstrip()
    if not refs:
        return answer

    parts = []
    for r in refs:
        fn = r.get("filename") or "unknown"
        extras = []
        if r.get("agency"): extras.append(f"Agency: {r['agency']}")
        if r.get("title"):  extras.append(f"Title: {r['title']}")
        if r.get("law"):    extras.append(f"Law: {r['law']}")

        if extras:
            parts.append(f"{fn} — " + "; ".join(extras))
        else:
            parts.append(fn)

    citations = "; ".join(parts)

    if answer and answer[-1] not in ".!?":
        answer += "."
    return f"{answer} {{{citations}}}"

def main():
    st.set_page_config(page_title="MS Regulations", layout="wide")
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
