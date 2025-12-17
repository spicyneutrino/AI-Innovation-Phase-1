import streamlit as st
from rag_engine import RAGEngine

KB_ID = "ENBRB90GYL"

def main():
    st.set_page_config(page_title="MS Regulations", layout="wide")
    st.title("Mississippi SoS Assistant")
    
    if 'engine' not in st.session_state:
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
                
                st.markdown(answer)
                
                if sources:
                    st.divider()
                    st.caption(f"Sources: {', '.join(sources)}")
        
        st.session_state.messages.append({"role": "assistant", "content": answer})

if __name__ == "__main__":
    main()