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
        st.info(f"**Q:** {safe_get(latest, 'question', '(no question)')}")
        st.success(f"**A:** {safe_get(latest, 'final_answer', '(no answer)')}")
        if safe_get(latest, "meta", {}):
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

    # Get schema first
    # Get schema first
    try:
        resp = requests.get(f"{API_URL}/preview", timeout=40)
        resp.raise_for_status()
        schema_data = resp.json()
    except Exception as e:
        st.error(f"Failed to load schema: {e}")
        st.stop()

    st.write("### Tables in Database:")

    for table, columns in schema_data.get("schema", {}).items():  # <-- use "schema"
        with st.expander(f"{table}"):
            st.write("Columns:", ", ".join(columns or []))

            preview_query = f"SELECT * FROM {table} LIMIT 20"

            try:
                preview = requests.post(
                    f"{API_URL}/preview",
                    json={"sql": preview_query},
                    timeout=10
                )
                preview.raise_for_status()
                rows = preview.json().get("rows", [])
                st.dataframe(rows)
            except Exception as e:
                st.error(f"Preview failed: {e}")

# ---------- CHAT TAB ----------
with chat_tab:
    st.title("Chat with your Assistant")

    # Initialize session state for chat if not already done
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "new_user_message" not in st.session_state:
        st.session_state.new_user_message = None
    if "history" not in st.session_state:
        st.session_state.history = []

    # Display the user's last question if chat history exists
    if st.session_state.messages:
        last_question = next(
            (msg["content"] for msg in reversed(st.session_state.messages) if msg.get("role") == "user"),
            None
        )
        if last_question:
            st.info(f"**Your last question was:** {last_question}")
        else:
            st.info("Start a new conversation by typing your question in the input box below.")
    else:
        st.info("No chat history available. Start a new conversation using the input below.")

    # Display previous chat messages with a limit for performance
    MAX_CHAT_MESSAGES = 20  # Limit to the last 20 messages for performance
    displayed_messages = st.session_state.messages[-MAX_CHAT_MESSAGES:]

    for msg in displayed_messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    # Handle new user input
    new_input = st.chat_input("Ask a question to the assistant:")
    if new_input:  # Triggered when the user sends a new message
        st.session_state.new_user_message = new_input
        st.session_state.messages.append({"role": "user", "content": new_input})
        with st.chat_message("user"):  # Display user message
            st.write(new_input)

        # Process the user message
        with st.chat_message("assistant"):  # Reserve container for assistant response
            with st.spinner("Processing your query..."):
                # Prepare payload for API call
                payload = {"message": new_input}
                try:
                    # Send the request and get the response
                    response = requests.post(f"{API_URL}/chat", json=payload, timeout=40)
                    response.raise_for_status()
                    data = response.json()

                    # Extract the final answer from the API response
                    assistant_text = data.get("final_answer", "(no answer received)")
                except Exception as e:
                    assistant_text = f"Sorry, I encountered an error: {e}"

                # Display the assistant's response
                st.write(assistant_text)
                # Add response to the chat history
                st.session_state.messages.append({"role": "assistant", "content": assistant_text})

    # Paginated history display
    if st.session_state.history:
        st.markdown("---")
        st.subheader("Recent History (Paginated)")
        num_items_per_page = 5
        page_count = (len(st.session_state.history) + num_items_per_page - 1) // num_items_per_page  # Total pages
        selected_page = st.number_input("Page", min_value=1, max_value=page_count, value=1, step=1)

        # Slice history for the current page
        start_idx = (selected_page - 1) * num_items_per_page
        end_idx = start_idx + num_items_per_page
        paginated_history = st.session_state.history[start_idx:end_idx]

        for i, item in enumerate(paginated_history, start=start_idx + 1):
            norm = normalize_history_item(item)
            st.markdown(f"**{i}. Q:** {norm['question']}")
            if sql := (norm.get("meta", {}).get("sql") or norm.get("meta", {}).get("query")):
                st.code(sql, language="sql")
            st.write(f"**A:** {norm['final_answer']}")