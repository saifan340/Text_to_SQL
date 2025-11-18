import os
import time
import requests
import streamlit as st
from dotenv import load_dotenv
from db import save_conversation, init_db

# --- Init ---
init_db()
load_dotenv()
API_URL = os.getenv("API_URL", "http://localhost:5000").rstrip("/")

st.set_page_config(page_title="Text-To-SQL App", layout="wide")

# --- Helpers ---

def safe_get(d, key, default="(missing)"):
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
    if not item:
        return {"question": "(empty)", "final_answer": "(empty)", "meta": {}}

    if "question" in item and "final_answer" in item:
        return {"question": item.get("question"), "final_answer": item.get("final_answer"), "meta": item.get("meta", {})}

    if "prompt" in item and "answer" in item:
        return {"question": item.get("prompt"), "final_answer": item.get("answer"), "meta": {"sql": item.get("sql", "")}}

    q = item.get("question") or item.get("prompt") or item.get("q") or "(unknown question)"
    a = item.get("final_answer") or item.get("answer") or item.get("final") or "(no answer)"
    meta = item.get("meta", {})
    return {"question": q, "final_answer": a, "meta": meta}


def add_history(question: str, final_answer: str, meta: dict = None):
    h = {"question": question, "final_answer": final_answer, "meta": meta or {}}
    st.session_state.history.insert(0, h)

# --- Session state defaults ---
if "history" not in st.session_state:
    st.session_state.history = []
if "messages" not in st.session_state:
    st.session_state.messages = []
if "user_id" not in st.session_state:
    st.session_state.user_id = "default_user"
if "new_user_message" not in st.session_state:
    st.session_state.new_user_message = None
if "pending" not in st.session_state:
    st.session_state.pending = False

# --- Layout header ---
st.markdown(
    """
    <h1 style="text-align:center; color:green;">Text-To-SQL</h1>
    <p style="text-align:center; color:gray;">Multi-page app with Home, Ask, Schema, Database Viewer and Health tabs.</p>
    <hr>
    """,
    unsafe_allow_html=True,
)

home_tab, chat_tab, ask_tab, schema_tab, db_tab, health_tab = st.tabs(
    ["Home", "Chat", "Ask", "Schema", "Database Viewer", "Health"]
)

# ---------------- HOME ----------------
with home_tab:
    st.subheader("Welcome to the Text-to-SQL App")
    st.markdown(
        """
        This app allows you to:
        - Ask natural language questions and get the answers as natural language 
        - Explore your database schema interactively 
        - View the latest conversation history and answers
        - Check the health of the backend API  
        - View the database schema 
        - Check if the backend API is running  
        ---
        Use the tabs above to get started!  
        """
    )
    st.image("https://streamlit.io/images/brand/streamlit-mark-color.png", width=200, caption="Powered by Streamlit + Flask")

# ---------------- ASK ----------------
with ask_tab:
    st.subheader("Ask your question to the DB")

    with st.form("ask_form"):
        user_id = st.text_input("User ID", value=st.session_state.get("user_id", "default_user"))
        question = st.text_area("Question", height=100, placeholder="Type your question for the DB...")
        submit = st.form_submit_button("Ask")

    if submit:
        if not question or not question.strip():
            st.warning("Please type a question.")
        else:
            st.session_state.user_id = user_id or "default_user"
            payload = {"user_id": st.session_state.user_id, "question": question}
            with st.spinner("Sending request to API..."):
                try:
                    resp = requests.post(f"{API_URL}/ask", json=payload, timeout=30)
                    resp.raise_for_status()
                    data = resp.json()
                    final_answer = data.get("final_answer") or data.get("answer") or data.get("final_answer_text") or "(no answer)"
                    meta = data.get("metadata", {})
                    add_history(question, final_answer, meta)
                    try:
                        save_conversation(st.session_state.get("user_id", "default_user"), question, "", final_answer)
                    except Exception:
                        pass
                    st.success("Answer received!")
                except Exception as e:
                    st.error(f"Error: {e}")

    if st.session_state.history:
        st.markdown("### Latest Answer")
        latest_raw = st.session_state.history[0]
        latest = normalize_history_item(latest_raw)
        st.info(f"**Q:** {safe_get(latest, 'question', '(no question)')}")
        st.success(f"**A:** {safe_get(latest, 'final_answer', '(no answer)')}")
        st.json(safe_get(latest, "meta", {}))

    if st.session_state.history:
        with st.expander("Conversation History"):
            for i, item in enumerate(st.session_state.history):
                norm = normalize_history_item(item)
                st.markdown(f"**{i + 1}. Q:** {norm['question']}")
                st.markdown(f"**A:** {norm['final_answer']}")
                if norm.get("meta"):
                    st.write(norm["meta"])
                st.markdown("---")

# ---------------- SCHEMA ----------------
with schema_tab:
    st.subheader("Database Schema")
    try:
        resp = requests.get(f"{API_URL}/schema", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        table_count = data.get("table_count", len(data.get("tables", {})))
        st.write(f"Found **{table_count} tables** in the database:")
        for table, cols in data.get("tables", {}).items():
            with st.expander(f"📁 {table}"):
                st.write(cols)
    except Exception as e:
        st.error(f"Could not load schema: {e}")

# ---------------- HEALTH ----------------
with health_tab:
    st.subheader("Health Check")
    try:
        resp = requests.get(f"{API_URL}/health", timeout=5)
        resp.raise_for_status()
        health = resp.json()
        st.success(f"Service is healthy: {health}")
    except Exception as e:
        st.error(f"API not healthy: {e}")

# ---------------- DB VIEWER ----------------
with db_tab:
    st.subheader("Database Viewer")
    try:
        resp = requests.get(f"{API_URL}/schema", timeout=10)
        resp.raise_for_status()
        schema_data = resp.json()

        st.write("### Tables in Database:")
        for table, columns in schema_data.get("tables", {}).items():
            with st.expander(f"{table}"):
                st.write("Columns:", ", ".join(columns))

                preview_query = f"SELECT * FROM {table} LIMIT 20"
                try:
                    # Try the text-to-sql 'prompt' payload first (backend expects 'prompt')
                    preview_resp = requests.post(f"{API_URL}/query", json={"prompt": preview_query}, timeout=20)
                    try:
                        preview_resp.raise_for_status()
                        preview_json = preview_resp.json()
                    except requests.HTTPError as e:
                        # If the server returned 400/422 for format mismatch, try dedicated preview endpoint
                        st.warning(f"Preview /query returned {preview_resp.status_code}; trying /table_preview... body={preview_resp.text}")
                        # fallback to table_preview
                        try:
                            fallback_resp = requests.post(f"{API_URL}/table_preview", json={"table": table}, timeout=20)
                            fallback_resp.raise_for_status()
                            preview_json = fallback_resp.json()
                        except Exception as e:
                            st.warning(f"Fallback preview failed: {e}")
                            preview_json = {}
                    results = preview_json.get("results") or preview_json.get("rows") or preview_json.get("data")
                    if results:
                        st.write("Preview (first 20 rows):")
                        st.dataframe(results)
                    else:
                        st.warning("Preview returned no results or unexpected format.")
                except Exception as e:
                    st.warning(f"Could not fetch preview: {e}")
    except Exception as e:
        st.error(f"Failed to load database schema: {e}")

# ---------------- CHAT (unified, input at bottom) ----------------
with chat_tab:
    st.title("Chat with your Assistant")

    # 1) Render all previous messages (oldest first)
    for m in st.session_state.messages:
        with st.chat_message(m.get("role", "assistant")):
            st.write(m.get("content", ""))

    # 2) If user sent a new message (pending), process it inline and show a local spinner
    if st.session_state.new_user_message and not st.session_state.pending:
        # mark pending to avoid double-send during reruns
        st.session_state.pending = True
        user_text = st.session_state.new_user_message
        # append user's message (visible immediately)
        st.session_state.messages.append({"role": "user", "content": user_text})

        # container where spinner will appear (right below the last message)
        with st.container():
            with st.spinner("Processing..."):
                try:
                    payload = {
                        "user_id": st.session_state.get("user_id", "default_user"),
                        "message": user_text
                    }
                    resp = requests.post(f"{API_URL}/chat", json=payload, timeout=40)
                    resp.raise_for_status()
                    data = resp.json()

                    final_answer = data.get("final_answer") or data.get("answer") or data.get("final_answer_text") or "(no answer)"
                    sql_query = data.get("sql_query") or data.get("sql")
                    db_results = data.get("db_results") or data.get("results")
                    is_db = data.get("is_db_question", False)

                except requests.HTTPError as e:
                    final_answer = f"Error from server: {e} — {resp.text if 'resp' in locals() else ''}"
                    sql_query = None
                    db_results = None
                    is_db = False
                except Exception as e:
                    final_answer = f"Error: {e}"
                    sql_query = None
                    db_results = None
                    is_db = False

        # replace spinner with assistant message
        assistant_display = final_answer
        if is_db and sql_query:
            assistant_display = f"**SQL:**\n```sql\n{sql_query}\n```\n**Answer:** {final_answer}"

        with st.chat_message("assistant"):
            # use st.markdown so SQL block renders nicely when present
            st.markdown(assistant_display)

        # save assistant message into state & history
        st.session_state.messages.append({"role": "assistant", "content": final_answer})
        add_history(user_text, final_answer, {"sql": sql_query, "results": db_results} if (sql_query or db_results) else {})

        # persist conversation to local DB (best-effort)
        try:
            save_conversation(st.session_state.get("user_id", "default_user"), user_text, sql_query or "", final_answer)
        except Exception:
            pass

        # clear pending flags and new_user_message
        st.session_state.new_user_message = None
        st.session_state.pending = False

        # rerun so the input box appears at the bottom after processing
        if hasattr(st, "experimental_rerun"):
            try:
                st.experimental_rerun()
            except Exception:
                pass

    # 3) Input always last (at bottom)
    new_input = st.chat_input("Ask your database a question...")
    if new_input:
        # prevent double-submit if already pending
        if st.session_state.pending:
            st.warning("Request already pending. Please wait.")
        else:
            st.session_state.new_user_message = new_input
            # immediate rerun so the pending flow runs in the next run
            if hasattr(st, "experimental_rerun"):
                try:
                    st.experimental_rerun()
                except Exception:
                    pass
            else:
                st.session_state._last_input_time = time.time()

    # 4) Show recent history (optional)
    if st.session_state.history:
        st.markdown("---")
        st.subheader("Recent history")
        for i, item in enumerate(st.session_state.history[:20], 1):
            norm = normalize_history_item(item)
            st.markdown(f"**{i}. Q:** {norm['question']}")
            if sql := (norm.get("meta", {}).get("sql") or norm.get("meta", {}).get("query")):
                st.code(sql, language="sql")
            st.write(f"**A:** {norm['final_answer']}")
