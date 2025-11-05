"""
streamlit_app.py - Streamlit frontend to interact with the Flask backend.

Features:
- Initializes session_state for messages/history.
- A small form to ask questions; posts to /chat with timeout.
- Shows messages, history, and a 'Schema' inspector button.
- Handles errors and displays them to the user.
- Improved schema display (dataframe) and automatically populates cached_schema.
"""

import os
import streamlit as st
import requests
import pandas as pd
from typing import Any, Dict, List, Optional

st.set_page_config(page_title="DB Chat UI", page_icon="💬", layout="centered")

# Backend API URL (adjust if needed)
API_URL = os.getenv("API_URL", "http://localhost:5000")

# Initialize session state buckets (safe defaults)
_defaults = {
    "messages": [],            # list of {"role": "user"|"assistant", "content": str}
    "history": [],             # list of {"question":..., "answer":..., "metadata":...}
    "user_id": "default_user",
    "last_schema": None,       # will hold dict from /schema
    "last_employees": None,    # will hold employees preview
    "cached_schema": None,     # optional, keep for compatibility
}
for _k, _v in _defaults.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

def add_history(user_question: str, answer: str, metadata: Dict[str, Any]):
    st.session_state.history.append({"question": user_question, "answer": answer, "metadata": metadata})

def schema_to_dataframe(schema: Dict[str, Any]) -> pd.DataFrame:
    """
    Convert common schema shapes into a flat DataFrame with columns:
    - table
    - column (name)
    - column_type (if available)
    Works for schema shaped like {"tables": {"table_name": ["col1","col2",...]}}
    or {"table_name": [{"name": "col1", "type": "TEXT"}, ...], ...}
    """
    rows = []
    if not schema:
        return pd.DataFrame(columns=["table", "column", "column_type"])
    # If top-level has "tables" key, use that
    tables = schema.get("tables") if isinstance(schema, dict) and "tables" in schema else schema
    # tables is now likely a dict mapping table->columns
    if isinstance(tables, dict):
        for table_name, cols in tables.items():
            # If cols is a list of strings
            if isinstance(cols, list) and cols and all(isinstance(c, str) for c in cols):
                for col in cols:
                    rows.append({"table": table_name, "column": col, "column_type": None})
            # If cols is a list of dicts with name/type
            elif isinstance(cols, list) and cols and all(isinstance(c, dict) for c in cols):
                for c in cols:
                    col_name = c.get("name") or c.get("column") or c.get("col") or None
                    col_type = c.get("type") or c.get("datatype") or None
                    rows.append({"table": table_name, "column": col_name, "column_type": col_type})
            else:
                # fallback: represent the raw value
                rows.append({"table": table_name, "column": str(cols), "column_type": None})
    else:
        # Unexpected shape; try to coerce to a readable DF
        rows.append({"table": "unknown", "column": str(schema), "column_type": None})

    df = pd.DataFrame(rows)
    # keep consistent column order
    return df[["table", "column", "column_type"]]

st.title("Chat with your Assistant (DB)")

with st.sidebar:
    st.markdown("## Controls")
    st.write(f"Backend: `{API_URL}`")

    # Fetch DB schema button: always attempt fetch when pressed
    if st.button("Fetch DB schema"):
        try:
            resp = requests.get(f"{API_URL}/schema", timeout=8)
            resp.raise_for_status()
            schema = resp.json()
            st.session_state.last_schema = schema
            # also populate cached_schema automatically for preview/compatibility
            st.session_state.cached_schema = schema
            st.success("Schema fetched (see below).")
        except Exception as e:
            st.error(f"Failed to fetch schema: {e}")

    # Show schema in the sidebar only if we have one
    if st.session_state.last_schema:
        st.subheader("Last fetched schema (flattened)")
        try:
            df = schema_to_dataframe(st.session_state.last_schema)
            st.dataframe(df)
        except Exception:
            # fallback to raw JSON if something unexpected happens
            st.json(st.session_state.last_schema)

    if st.button("Preview employees"):
        try:
            resp = requests.get(f"{API_URL}/employees", timeout=8)
            resp.raise_for_status()
            preview = resp.json()
            st.session_state.last_employees = preview
            st.success("Employees preview fetched.")
            st.write(preview)
        except Exception as e:
            st.error(f"Failed to fetch employees: {e}")

    if st.button("Preview Database"):
        try:
            resp = requests.get(f"{API_URL}/schema", timeout=10)
            resp.raise_for_status()
            schema_data = resp.json()

            st.write("### Tables in Database:")
            # If schema_data is complex, we still try to show a flattened view
            try:
                df_preview = schema_to_dataframe(schema_data)
                st.dataframe(df_preview)
            except Exception:
                # fallback to expanders with column lists
                for table, columns in (schema_data.get("tables") or {}).items():
                    with st.expander(f"{table}"):
                        st.write("Columns:", ", ".join(columns))

            for table, columns in (schema_data.get("tables") or {}).items():
                with st.expander(f"{table} - preview rows"):
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

    st.markdown("---")
    st.write("Session history stored in-memory for this session only.")

# Show schema or employees previews (main area) if present
if st.session_state.last_schema:
    st.subheader("DB Schema (sidebar fetch)")
    try:
        df_main = schema_to_dataframe(st.session_state.last_schema)
        st.dataframe(df_main)
    except Exception:
        st.json(st.session_state.last_schema)

if st.session_state.last_employees:
    st.subheader("Employees preview (sidebar fetch)")
    st.write(st.session_state.last_employees)

if st.session_state.cached_schema:
    st.subheader("Cached schema (auto-populated on fetch)")
    try:
        st.dataframe(schema_to_dataframe(st.session_state.cached_schema))
    except Exception:
        st.write(st.session_state.cached_schema)

st.subheader("Ask a question")

with st.form("ask_form"):
    st.session_state.user_id = st.text_input("User ID", value=st.session_state.user_id)
    user_question = st.text_area(
        "Question",
        value="",
        height=120,
        placeholder="Examples: 'list employees', 'count employees', 'employee 2', 'employee named Alice'",
    )
    submitted = st.form_submit_button("Send")

if submitted:
    if not user_question or not user_question.strip():
        st.warning("Please type a question.")
    elif len(user_question) > 500:
        st.error("Your question is too long. Questions should be under 500 characters.")
    elif "<script>" in user_question.lower():
        st.error("Invalid characters detected in your question.")
    else:
        # Process valid input
        st.session_state.messages.append({"role": "user", "content": user_question})

        with st.spinner("Querying backend..."):
            try:
                headers = {"Content-Type": "application/json"}
                payload = {"user_id": st.session_state.user_id, "user_question": user_question}
                resp = requests.post(
                    f"{API_URL}/ask",
                    json=payload,
                    headers=headers,
                    timeout=15,
                )
                # If status code is not 200..299, raise so we can inspect the body
                try:
                    resp.raise_for_status()
                except requests.exceptions.HTTPError:
                    st.error(f"Request failed: {resp.status_code} - {resp.reason}")
                    st.code(resp.text, language="json")
                    st.session_state.messages.append(
                        {"role": "assistant", "content": f"Server error: {resp.status_code} - {resp.text}"})
                    add_history(user_question, f"Server error: {resp.status_code}", {"raw_response": resp.text})
                    raise

                data = resp.json()

                final_answer = data.get("final_answer", "")
                sql_query = data.get("sql_query")
                sql_params = data.get("sql_params", [])
                rows = data.get("rows", [])

                assistant_content_lines = [final_answer]
                if sql_query:
                    assistant_content_lines.append("\nSQL (safe): " + sql_query)
                    if sql_params:
                        assistant_content_lines.append("Params: " + str(sql_params))
                if rows:
                    assistant_content_lines.append("\nRows preview (first items):")
                    assistant_content_lines.append(str(rows[:10]))

                assistant_content = "\n".join(assistant_content_lines)
                st.session_state.messages.append({"role": "assistant", "content": assistant_content})
                add_history(user_question, final_answer,
                            {"sql": sql_query, "sql_params": sql_params, "rows_preview": len(rows)})
                st.success("Answer received.")

            except requests.exceptions.RequestException as e:
                err = f"Request failed: {e}"
                st.session_state.messages.append({"role": "assistant", "content": err})
                add_history(user_question, err, {})
                st.error(err)

# Display chat messages
st.markdown("----")
st.subheader("Chat")
chat_history = "\n".join([
    f"**You:** {msg['content']}" if msg['role'] == "user" else f"**Assistant:** {msg['content']}"
    for msg in st.session_state.messages
])
st.markdown(chat_history)

# Display history
st.markdown("----")
st.subheader("History")
if not st.session_state.history:
    st.write("_No history yet._")
else:
    history_md = ""
    for i, h in enumerate(reversed(st.session_state.history[-50:]), 1):
        history_md += f"**Q{i}:** {h['question']}\n- **A:** {h['answer']}\n"
        metadata = h.get("metadata", {})
        if metadata:
            summarized_meta = {k: str(v)[:50] + '...' if len(str(v)) > 50 else v for k, v in metadata.items()}
    st.markdown(history_md)

st.markdown("----")
st.write("Tip: This demo uses a tiny whitelist to turn simple natural questions into SQL. "
         "It avoids allowing arbitrary SQL from the UI for safety.")
