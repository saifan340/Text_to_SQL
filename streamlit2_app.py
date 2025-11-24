import streamlit as st
import requests
import pandas as pd
import json
from typing import Any, Dict, List, Optional

st.set_page_config(page_title="Text-to-SQL Frontend", layout="wide")

DEFAULT_BASE_URL = "http://localhost:5000"

# ---------- Helpers ----------

def api_get(base: str, path: str) -> Dict[str, Any]:
    url = base.rstrip("/") + path
    resp = requests.get(url, timeout=10)
    try:
        return {"ok": resp.ok, "status_code": resp.status_code, "json": resp.json()}
    except Exception:
        return {"ok": resp.ok, "status_code": resp.status_code, "text": resp.text}


def api_post(base: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = base.rstrip("/") + path
    headers = {"Content-Type": "application/json"}
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    try:
        return {"ok": resp.ok, "status_code": resp.status_code, "json": resp.json()}
    except Exception:
        return {"ok": resp.ok, "status_code": resp.status_code, "text": resp.text}


def to_dataframe(maybe_rows: Any) -> Optional[pd.DataFrame]:
    """Convert typical DB results (list of dicts / list of tuples) to DataFrame when possible."""
    if maybe_rows is None:
        return None
    if isinstance(maybe_rows, list) and len(maybe_rows) > 0:
        first = maybe_rows[0]
        # list of dicts
        if isinstance(first, dict):
            return pd.DataFrame(maybe_rows)
        # list of lists/tuples
        if isinstance(first, (list, tuple)):
            # try to make columns numeric
            try:
                df = pd.DataFrame(maybe_rows)
                return df
            except Exception:
                return None
    # single dict
    if isinstance(maybe_rows, dict):
        return pd.DataFrame([maybe_rows])
    return None


# ---------- Session state ----------

if "conversations" not in st.session_state:
    st.session_state.conversations = []  # local mirror of saved convos
if "show_db_viewer" not in st.session_state:
    st.session_state.show_db_viewer = False


# ---------- UI layout ----------

with st.sidebar:
    st.title("Settings")
    base_url = st.text_input("Backend base URL", value=DEFAULT_BASE_URL)
    user_id = st.text_input("User ID (for /ask and /chat)", value="default_user")
    st.markdown("---")
    st.caption("Tools")
    if st.button("Health check"):
        res = api_get(base_url, "/health")
        st.json(res)
    if st.button("Get schema"):
        res = api_get(base_url, "/schema")
        st.json(res)

    # Toggle button for DB viewer at the bottom
    if st.button("Toggle DB viewer (bottom)"):
        # flip the flag
        st.session_state.show_db_viewer = not st.session_state.show_db_viewer
        if st.session_state.show_db_viewer:
            st.success("DB viewer enabled — scroll to the bottom to view saved conversations")
        else:
            st.info("DB viewer disabled")


st.header("Text-to-SQL — Streamlit Frontend")
st.write("Connects to your Flask Text-to-SQL backend. Choose a tab and interact with endpoints.")

mode = st.tabs(["Chat (smart)", "Ask (with memory)", "Natural->SQL (/query)", "Run SQL (direct)", "Schema & Health"])

# ---- Chat Tab ----
with mode[0]:
    st.subheader("Chat (smart) — POST /chat")
    message = st.text_area("Message (natural question or SQL)", height=120)
    cols = st.columns([1, 1, 1])
    with cols[0]:
        if st.button("Send to /chat"):
            if not message.strip():
                st.error("Please enter a message.")
            else:
                payload = {"user_id": user_id, "message": message}
                with st.spinner("Calling /chat..."):
                    res = api_post(base_url, "/chat", payload)
                st.subheader("Response")
                st.json(res)
                # save local copy
                try:
                    body = res.get("json")
                    st.session_state.conversations.append({"endpoint": "/chat", "request": payload, "response": body})
                except Exception:
                    pass
    with cols[1]:
        if st.button("Execute as direct SQL (send trimmed message)"):
            if not message.strip():
                st.error("Please enter a message.")
            else:
                # If message is raw SQL this will be executed server-side by /chat
                payload = {"user_id": user_id, "message": message}
                with st.spinner("Executing SQL via /chat..."):
                    res = api_post(base_url, "/chat", payload)
                st.subheader("Response")
                st.json(res)
    with cols[2]:
        if st.button("Clear local conversation cache"):
            st.session_state.conversations = []
            st.success("Cleared")

    if st.session_state.conversations:
        st.subheader("Local conversation history (this session)")
        for i, c in enumerate(reversed(st.session_state.conversations[-20:])):
            st.markdown(f"**{c['endpoint']}** — request:")
            st.json(c["request"])
            st.markdown("response:")
            st.json(c.get("response"))

# ---- Ask Tab ----
with mode[1]:
    st.subheader("Ask (with memory) — POST /ask")
    question = st.text_area("Question for /ask", height=120)
    ask_cols = st.columns([1, 1])
    with ask_cols[0]:
        if st.button("Ask"):
            if not question.strip():
                st.error("Please enter a question.")
            else:
                payload = {"user_id": user_id, "question": question}
                with st.spinner("Calling /ask..."):
                    res = api_post(base_url, "/ask", payload)
                st.subheader("Response")
                st.json(res)
                try:
                    st.session_state.conversations.append({"endpoint": "/ask", "request": payload, "response": res.get("json")})
                except Exception:
                    pass
    with ask_cols[1]:
        st.markdown("### Quick examples")
        if st.button("How many employees are in Sales?"):
            st.write("Sending example — feel free to edit")
            st.session_state.question = "How many employees are in the Sales department?"
            question = st.session_state.question

# ---- Natural -> SQL Tab (/query) ----
with mode[2]:
    st.subheader("Natural language → SQL (/query)")
    nl_prompt = st.text_area("Natural language prompt (will generate SQL)", height=140)
    qcols = st.columns([1, 1, 1])
    with qcols[0]:
        if st.button("Generate SQL and run (/query)"):
            if not nl_prompt.strip():
                st.error("Please enter a prompt")
            else:
                payload = {"prompt": nl_prompt}
                with st.spinner("Calling /query..."):
                    res = api_post(base_url, "/query", payload)
                st.subheader("Response")
                st.json(res)
                try:
                    st.session_state.conversations.append({"endpoint": "/query", "request": payload, "response": res.get("json")})
                except Exception:
                    pass
    with qcols[1]:
        st.markdown("#### Sample prompts")
        if st.button("List employees with salary > 50000"):
            nl_prompt = "List employees with salary greater than 50000 and their department"
            st.session_state.nl_prompt = nl_prompt

# ---- Run SQL (direct) ----
with mode[3]:
    st.subheader("Run raw SQL (send to /chat as direct SQL)")
    raw_sql = st.text_area("Raw SQL to execute", height=160)
    rcols = st.columns([1, 1])
    with rcols[0]:
        if st.button("Run SQL"):
            if not raw_sql.strip():
                st.error("Please enter SQL")
            else:
                # Use /chat to allow the backend to detect and run direct SQL
                payload = {"user_id": user_id, "message": raw_sql}
                with st.spinner("Executing SQL via /chat..."):
                    res = api_post(base_url, "/chat", payload)
                st.subheader("Response")
                st.json(res)
                # try to show tabular results
                try:
                    body = res.get("json") or {}
                    db_res = body.get("db_results") if isinstance(body, dict) else None
                    df = to_dataframe(db_res)
                    if df is not None:
                        st.dataframe(df)
                except Exception:
                    pass
    with rcols[1]:
        if st.button("Explain SQL (send as natural question)"):
            if not raw_sql.strip():
                st.error("Enter SQL to explain")
            else:
                payload = {"user_id": user_id, "message": f"Explain this SQL: {raw_sql}"}
                with st.spinner("Calling /chat to explain SQL..."):
                    res = api_post(base_url, "/chat", payload)
                st.json(res)

# ---- Schema & Health Tab ----
with mode[4]:
    st.subheader("Schema & Health")
    if st.button("Get /schema"):
        res = api_get(base_url, "/schema")
        st.json(res)
        if isinstance(res.get("json"), dict):
            tables = res.get("json").get("tables")
            if tables:
                st.markdown("### Tables")
                st.write(tables)

    if st.button("Health check (/health)"):
        res = api_get(base_url, "/health")
        st.json(res)

    st.markdown("---")
    st.markdown("### Local session conversations")
    for i, c in enumerate(reversed(st.session_state.conversations[-50:])):
        st.markdown(f"**{i+1}. {c['endpoint']}**")
        st.write("Request:")
        st.json(c["request"])
        st.write("Response:")
        st.json(c.get("response"))

# ---- Bottom DB viewer (toggleable) ----
st.markdown("---")
if st.session_state.show_db_viewer:
    st.markdown("## Conversation DB Viewer (bottom)")
    st.write("This viewer attempts to fetch saved conversations from the backend endpoint `/history?user_id=<user_id>`. If the backend does not provide that endpoint, you'll see an error and the local session cache instead.")

    # Try backend first
    try:
        res = api_get(base_url, f"/history?user_id={user_id}")
        if res.get("ok") and isinstance(res.get("json"), list):
            data = res.get("json")
            st.markdown("**Backend conversation table**")
            df = to_dataframe(data)
            if df is not None:
                st.dataframe(df)
            else:
                st.json(data)
        else:
            # backend returned non-list or not ok
            st.warning(f"Backend /history returned status {res.get('status_code')}. Showing local session cache instead.")
            if st.session_state.conversations:
                combined = []
                for c in reversed(st.session_state.conversations[-200:]):
                    item = {
                        "endpoint": c.get("endpoint"),
                        "request": json.dumps(c.get("request"), ensure_ascii=False),
                        "response": json.dumps(c.get("response"), ensure_ascii=False)
                    }
                    combined.append(item)
                df_local = pd.DataFrame(combined)
                st.dataframe(df_local)
            else:
                st.info("No local conversations in this Streamlit session yet.")
    except Exception as e:
        st.error(f"Error fetching /history: {e}. Showing local session cache instead.")
        if st.session_state.conversations:
            combined = []
            for c in reversed(st.session_state.conversations[-200:]):
                item = {
                    "endpoint": c.get("endpoint"),
                    "request": json.dumps(c.get("request"), ensure_ascii=False),
                    "response": json.dumps(c.get("response"), ensure_ascii=False)
                }
                combined.append(item)
            df_local = pd.DataFrame(combined)
            st.dataframe(df_local)
        else:
            st.info("No local conversations in this Streamlit session yet.")

# Footer
st.markdown("---")
st.caption("This Streamlit app assumes your Flask backend is reachable at the configured base URL. Adjust the URL in the sidebar if the server runs elsewhere.")
