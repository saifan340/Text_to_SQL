import os
import requests
import streamlit as st
from dotenv import load_dotenv
from db import save_conversation
from db import init_db
init_db()
load_dotenv()
API_URL = os.getenv("API_URL", "http://localhost:5000").rstrip("/")

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

    # Slightly different shape from ask_tab insertion (question, final_answer, meta)
    if "question" in item and "final_answer" not in item and "final_answer" in item:
        return {"question": item.get("question"), "final_answer": item.get("final_answer"), "meta": item.get("meta", {})}
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
st.markdown(
    """
    <h1 style="text-align:center; color:green;">
         Text-To-SQL 
    </h1>
    <p style="text-align:center; color:gray;">
        Multi-page app with Home, Ask, Schema, Database Viewer and Health tabs.
    </p>
    <hr>
    """,
    unsafe_allow_html=True
)

home_tab, chat_tab, ask_tab, schema_tab, db_tab, health_tab = st.tabs(
    ["Home", "Chat", "Ask", "Schema", "Database Viewer", "Health"]
)
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
    st.image(
        "https://streamlit.io/images/brand/streamlit-mark-color.png",
        width=200,
        caption="Powered by Streamlit + Flask"
    )
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
        st.write("DEBUG: latest =", latest_raw)
        st.write("DEBUG: type(latest_raw) =", type(latest_raw))
        if isinstance(latest_raw, dict):
            st.write("DEBUG: keys:", list(latest_raw.keys()))
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
with health_tab:
    st.subheader("Health Check")
    try:
        resp = requests.get(f"{API_URL}/health", timeout=5)
        resp.raise_for_status()
        health = resp.json()
        st.success(f"Service is healthy: {health}")
    except Exception as e:
        st.error(f"API not healthy: {e}")
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
                    preview_resp = requests.post(f"{API_URL}/query", json={"prompt": preview_query}, timeout=20)
                    preview_resp.raise_for_status()
                    preview_json = preview_resp.json()
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

# ---------- CHAT TAB ----------
with chat_tab:
    st.title("Chat with your Assistant")

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "history" not in st.session_state:
        st.session_state.history = []

    if st.session_state.messages:
        last_question = next(
            (msg["content"] for msg in reversed(st.session_state.messages) if msg.get("role") == "user"),
            None
        )
        if last_question:
            st.write(f"**Your last question was:** {last_question}")
        else:
            st.write("No user questions found in the conversation.")
    else:
        st.write("No chat history available.")

    # Display previous chat messages
    for m in st.session_state.messages:
        role = m.get("role", "assistant")
        with st.chat_message(role):
            st.markdown(m.get("content", ""))

    # Handle new user input
    if user_input := st.chat_input("Ask your database a question..."):
        with st.chat_message("user"):
            st.markdown(user_input)
        st.session_state.messages.append({"role": "user", "content": user_input})

        payload = {
            "user_id": st.session_state.get("user_id", "default_user"),
            "message": user_input
        }

        with st.spinner("Processing..."):
            try:
                resp = requests.post(f"{API_URL}/chat", json=payload, timeout=40)
                resp.raise_for_status()
                data = resp.json()

                final_answer = data.get("final_answer", "(no answer)")
                sql_query = data.get("sql_query")
                db_results = data.get("db_results")
                is_db = data.get("is_db_question", False)

                if is_db and sql_query:
                   with st.chat_message("assistant"):
                       st.markdown(f"**SQL:**\n```sql\n{sql_query}\n```\n**Answer:** {final_answer}")
                else:
                    #assistant_content = final_answer
                    with st.chat_message("assistant"):
                         st.markdown(final_answer)

                st.session_state.messages.append({"role": "assistant", "content": final_answer})
                add_history(user_input, final_answer, {"sql": sql_query, "results": db_results})

            except Exception as e:
                err = f"Error: {e}"
                with st.chat_message("assistant"):
                     st.markdown(err)
                st.session_state.messages.append({"role": "assistant", "content": err})
                #add_history(user_input, err, {})
                add_history(user_input, err, {})

    # Show previous conversation history
    if st.session_state.history:
        st.markdown("---")
        st.subheader("Recent history")
        for i, item in enumerate(st.session_state.history[:20], 1):
            norm = normalize_history_item(item)
            st.markdown(f"**{i}. Q:** {norm['question']}")
            if sql := (norm.get("meta", {}).get("sql") or norm.get("meta", {}).get("query")):
                st.code(sql, language="sql")
            st.write(f"**A:** {norm['final_answer']}")
