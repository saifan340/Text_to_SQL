import os
import requests
import streamlit as st
from dotenv import load_dotenv
from db import save_conversation
from db import init_db
from config import API_URL
init_db()
load_dotenv()
API_URL = os.getenv("API_URL", "http://localhost:5000").rstrip("/")
#API_URL =  "http://localhost:5000"


st.set_page_config(page_title="Text-To-SQL App", layout="wide")

def safe_get(d, key, default="(missing)"):
    """Safely get key from dict-like object. Return default on failure."""
    try:
        if d is None:
            return default
        if isinstance(d, dict):
            return d.get(key, default)
        if hasattr(d, "get"):
            return d.get(key, default)
        try:
            return d[key]
        except Exception:
            return str(d)
    except Exception:
        return default
def normalize_history_item(item: dict) -> dict:
    """
    Normalize different history item shapes to a consistent structure:
    {
        "question": str,
        "final_answer": str,
        "meta": dict (optional)
    }
    """
    if not item:
        return {"question": "(empty)", "final_answer": "(empty)", "meta": {}}

    # Already normalized
    if "question" in item and "final_answer" in item:
        return {"question": item.get("question"), "final_answer": item.get("final_answer"), "meta": item.get("meta", {})}

    # Older shape from chat_tab: prompt/sql/answer
    if "prompt" in item and "answer" in item:
        return {"question": item.get("prompt"), "final_answer": item.get("answer"), "meta": {"sql": item.get("sql", "")}}

    # Note: The above condition was logically impossible (checking for both presence and absence)
    # Removed redundant condition
    q = item.get("question") or item.get("prompt") or item.get("q") or "(unknown question)"
    a = item.get("final_answer") or item.get("answer") or item.get("final") or "(no answer)"
    meta = item.get("meta", {})
    return {"question": q, "final_answer": a, "meta": meta}


def add_history(question: str, final_answer: str, meta: dict = None):
    """Insert a normalized history item at top (index 0)."""
    h = {"question": question, "final_answer": final_answer, "meta": meta or {}}
    st.session_state.history.insert(0, h)
if "history" not in st.session_state:
    st.session_state.history = []
if "messages" not in st.session_state:
    st.session_state.messages = []
if "user_id" not in st.session_state:
    st.session_state.user_id = "default_user"
st.markdown("""
   
    <h1 style="text-align:center; color:green;">
         QueryAI
    </h1>
    <p style="text-align:center; color:gray;">
        Multi-page app with Home, Chat, Ask, Schema, Database Viewer and Health tabs.
    </p>
    <hr>
      
    """,
    unsafe_allow_html=True
)

home_tab, chat_tab, ask_tab, schema_tab, db_tab, health_tab = st.tabs(
    ["Home", "Chat", "Ask", "Schema", "Database Viewer", "Health"]
)

# ---------- CHAT TAB ----------
with chat_tab:
    # --- Chat tab: replace your current `with tab1:` block with this ---

        st.header("Chat")

        # Ensure session state chat history exists
        if "messages" not in st.session_state:
            st.session_state["messages"] = [
                {"role": "system", "content": "You are an assistant."}
            ]

        # Render chat history
        for msg in st.session_state["messages"]:
            role = msg.get("role", "assistant")
            content = msg.get("content", "")
            # Use Streamlit chat message UI if available
            try:
                with st.chat_message(role):
                    st.write(content)
            except Exception:
                # Fallback if st.chat_message not available
                if role == "user":
                    st.markdown(f"**You:** {content}")
                elif role == "assistant":
                    st.markdown(f"**Assistant:** {content}")
                else:
                    st.markdown(content)

        # Get user input
        user_input = st.chat_input("Ask a question or enter a prompt...")

        if user_input:
            # Append user message to history and render immediately
            st.session_state["messages"].append({"role": "user", "content": user_input})
            with st.chat_message("user"):
                st.write(user_input)

            # Call your Flask /query endpoint
            url = f"{API_URL}/query"
            payload = {"prompt": user_input}
            headers = {"Content-Type": "application/json"}

            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except requests.exceptions.RequestException as e:
                error_text = f"Request to /query failed: {e}"
                with st.chat_message("assistant"):
                    st.write(error_text)
                st.session_state["messages"].append({"role": "assistant", "content": error_text})
            else:
                # Try common keys for assistant text
                assistant_text = (
                        data.get("final_answer")
                        or data.get("assistant_text")
                        or data.get("final")
                        or data.get("answer")
                        or data.get("message")
                        or "(no answer received)"
                )

                # If the API returned only SQL/results, optionally summarise or display them
                # But we won't change structure — just display assistant_text and the SQL/results below:
                with st.chat_message("assistant"):
                    st.write(assistant_text)

                    # Optionally show the generated/executed SQL (if present)
                    sql = data.get("sql")
                    if sql:
                        st.markdown("**Generated / executed SQL:**")
                        st.code(sql, language="sql")

                    # Optionally show tabular results if present
                    results = data.get("results")
                    if isinstance(results, list) and results:
                        try:
                            # Convert to DataFrame for nicer display if possible
                            import pandas as _pd

                            df = _pd.DataFrame(results)
                            st.dataframe(df)
                        except Exception:
                            st.write(results)
                    # Provide raw JSON expand for debugging
                    st.expander("Raw response JSON", expanded=False)
                    st.write(data)

                # Append assistant response to history
                st.session_state["messages"].append({"role": "assistant", "content": assistant_text})

            # (No structural changes elsewhere — do not call experimental_rerun here)
