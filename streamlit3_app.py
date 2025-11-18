import os
import requests
import streamlit as st
import logging
from dotenv import load_dotenv
from config import MODEL_NAME
from openai_service import call_openai_for_sql, call_openai_for_answer, call_openai_for_not_db_answer
from db import run_sql, save_conversation
from utils import get_schema_text_from_db
from db import init_db
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize database
init_db()
load_dotenv()

# Constants
API_URL = os.getenv("API_URL", "http://localhost:5000").rstrip("/")
DEFAULT_USER_ID = "default_user"
REQUEST_TIMEOUT = 30
MAX_PREVIEW_ROWS = 20


# ==================== DATA MODELS ====================
@dataclass
class ConversationEntry:
    """Represents a single conversation entry"""
    question: str
    final_answer: str
    sql_query: Optional[str] = None
    db_results: Optional[List[Dict]] = None
    timestamp: Optional[str] = None
    is_db_question: bool = False

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        return {
            "question": self.question,
            "final_answer": self.final_answer,
            "meta": {
                "sql": self.sql_query,
                "results": self.db_results,
                "is_db": self.is_db_question,
                "timestamp": self.timestamp
            }
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationEntry':
        """Create from dictionary (handles multiple formats)"""
        if not data:
            return cls(question="(empty)", final_answer="(empty)")

        # New format
        if "question" in data and "final_answer" in data:
            meta = data.get("meta", {})
            return cls(
                question=data["question"],
                final_answer=data["final_answer"],
                sql_query=meta.get("sql"),
                db_results=meta.get("results"),
                timestamp=meta.get("timestamp"),
                is_db_question=meta.get("is_db", False)
            )

        # Legacy format (prompt/answer)
        if "prompt" in data and "answer" in data:
            return cls(
                question=data["prompt"],
                final_answer=data["answer"],
                sql_query=data.get("sql"),
                db_results=data.get("results")
            )

        # Fallback for unknown formats
        question = data.get("question") or data.get("prompt") or data.get("q") or "(unknown)"
        answer = data.get("final_answer") or data.get("answer") or data.get("final") or "(no answer)"
        return cls(question=question, final_answer=answer)


# ==================== API CLIENT ====================
class APIError(Exception):
    """Custom exception for API errors"""
    pass


class APIClient:
    """Client for communicating with the backend API"""

    def __init__(self, base_url: str = API_URL, timeout: int = REQUEST_TIMEOUT):
        self.base_url = base_url
        self.timeout = timeout
        self.session = requests.Session()
    def query(self, prompt: str) -> Dict[str, Any]:
        """Execute a query"""
        return self._post("/query", {"prompt": prompt}, timeout=20)

    def ask(self, user_id: str, question: str) -> Dict[str, Any]:
        """Ask a question via the /ask endpoint"""
        return self._post("/ask", {"user_id": user_id, "question": question})

    def chat(self, user_id: str, message: str) -> Dict[str, Any]:
        """Send a chat message via the /chat endpoint"""
        return self._post("/chat", {"user_id": user_id, "message": message})

    def get_schema(self) -> Dict[str, Any]:
        """Get database schema"""
        return self._get("/schema")

    def get_health(self) -> Dict[str, Any]:
        """Check API health"""
        return self._get("/health", timeout=5)

    def query(self, prompt: str) -> Dict[str, Any]:
        """Execute a query"""
        return self._post("/query", {"prompt": prompt}, timeout=20)

    def _get(self, endpoint: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        """Execute GET request"""
        try:
            url = f"{self.base_url}{endpoint}"
            logger.debug(f"GET {url}")
            resp = self.session.get(url, timeout=timeout or self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.Timeout:
            logger.error(f"Timeout on GET {endpoint}")
            raise APIError(f"Request timed out after {timeout or self.timeout}s")
        except requests.HTTPError as e:
            logger.error(f"HTTP error on GET {endpoint}: {e.response.status_code}")
            raise APIError(f"HTTP error {e.response.status_code}")
        except requests.RequestException as e:
            logger.error(f"Request error on GET {endpoint}: {e}")
            raise APIError(f"Connection error: {str(e)}")
        except ValueError as e:
            logger.error(f"JSON decode error on GET {endpoint}: {e}")
            raise APIError("Invalid JSON response from server")

    def _post(self, endpoint: str, data: Dict, timeout: Optional[int] = None) -> Dict[str, Any]:
        """Execute POST request"""
        try:
            url = f"{self.base_url}{endpoint}"
            logger.debug(f"POST {url}")
            resp = self.session.post(url, json=data, timeout=timeout or self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.Timeout:
            logger.error(f"Timeout on POST {endpoint}")
            raise APIError(f"Request timed out after {timeout or self.timeout}s")
        except requests.HTTPError as e:
            logger.error(f"HTTP error on POST {endpoint}: {e.response.status_code}")
            raise APIError(f"HTTP error {e.response.status_code}")
        except requests.RequestException as e:
            logger.error(f"Request error on POST {endpoint}: {e}")
            raise APIError(f"Connection error: {str(e)}")
        except ValueError as e:
            logger.error(f"JSON decode error on POST {endpoint}: {e}")
            raise APIError("Invalid JSON response from server")


# ==================== UTILITY FUNCTIONS ====================
def safe_get(d: any, key: str, default: str = "(missing)") -> str:
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


def add_history(question: str, final_answer: str, meta: dict = None):
    """Insert a normalized history item at top (index 0)."""
    entry = ConversationEntry(
        question=question,
        final_answer=final_answer,
        sql_query=meta.get("sql") if meta else None,
        db_results=meta.get("results") if meta else None
    )
    st.session_state.history.insert(0, entry.to_dict())
    logger.info(f"Added to history: {question[:50]}...")


def add_message(role: str, content: str):
    """Add message to chat"""
    st.session_state.messages.append({"role": role, "content": content})


def clear_chat():
    """Clear chat messages"""
    st.session_state.messages = []
    logger.info("Chat cleared")


# ==================== SESSION STATE INITIALIZATION ====================
if "history" not in st.session_state:
    st.session_state.history = []
if "messages" not in st.session_state:
    st.session_state.messages = []
if "user_id" not in st.session_state:
    st.session_state.user_id = DEFAULT_USER_ID

# Initialize API client
api_client = APIClient()

# ==================== PAGE CONFIGURATION ====================
st.set_page_config(page_title="Text-To-SQL App", layout="wide")

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

# ==================== CREATE TABS ====================
home_tab, chat_tab, ask_tab, schema_tab, db_tab, health_tab = st.tabs(
    ["🏠 Home", "💬 Chat", "❓ Ask", "📊 Schema", "🗄️ Database Viewer", "❤️ Health"]
)

# ==================== HOME TAB ====================
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

# ==================== ASK TAB ====================
with ask_tab:
    st.subheader("Ask your question to the DB")

    with st.form("ask_form"):
        user_id = st.text_input("User ID", value=st.session_state.get("user_id", DEFAULT_USER_ID))
        question = st.text_area("Question", height=100, placeholder="Type your question for the DB...")
        submit = st.form_submit_button("Ask")

    if submit:
        if not question or not question.strip():
            st.warning("Please type a question.")
        else:
            st.session_state.user_id = user_id or DEFAULT_USER_ID

            with st.spinner("Sending request to API..."):
                try:
                    data = api_client.ask(st.session_state.user_id, question)

                    final_answer = (
                            data.get("final_answer") or
                            data.get("answer") or
                            data.get("final_answer_text") or
                            "(no answer)"
                    )
                    meta = data.get("metadata", {})

                    add_history(question, final_answer, meta)

                    try:
                        save_conversation(st.session_state.user_id, question, "", final_answer)
                    except Exception as e:
                        logger.warning(f"Failed to save conversation: {e}")

                    st.success("Answer received!")

                except APIError as e:
                    st.error(f"Error: {e}")
                    logger.error(f"API error in ask_tab: {e}")

    # Display latest answer
    if st.session_state.history:
        st.markdown("### Latest Answer")
        latest_entry = ConversationEntry.from_dict(st.session_state.history[0])

        st.info(f"**Q:** {latest_entry.question}")
        st.success(f"**A:** {latest_entry.final_answer}")

        if latest_entry.sql_query or latest_entry.db_results:
            meta_dict = {}
            if latest_entry.sql_query:
                meta_dict["sql"] = latest_entry.sql_query
            if latest_entry.db_results:
                meta_dict["results"] = latest_entry.db_results
            st.json(meta_dict)

    # Conversation history
    if st.session_state.history:
        with st.expander("Conversation History"):
            for i, item in enumerate(st.session_state.history):
                entry = ConversationEntry.from_dict(item)
                st.markdown(f"**{i + 1}. Q:** {entry.question}")
                st.markdown(f"**A:** {entry.final_answer}")
                if entry.sql_query:
                    st.code(entry.sql_query, language="sql")
                st.markdown("---")

# ==================== SCHEMA TAB ====================
with schema_tab:
    st.subheader("Database Schema")
    try:
        data = api_client.get_schema()
        table_count = data.get("table_count", len(data.get("tables", {})))
        st.write(f"Found **{table_count} tables** in the database:")

        for table, cols in data.get("tables", {}).items():
            with st.expander(f"📁 {table}"):
                st.write(cols)
    except APIError as e:
        st.error(f"Could not load schema: {e}")
        logger.error(f"Schema loading error: {e}")

# ==================== HEALTH TAB ====================
with health_tab:
    st.subheader("Health Check")
    try:
        health = api_client.get_health()
        st.success(f"Service is healthy: {health}")
    except APIError as e:
        st.error(f"API not healthy: {e}")
        logger.error(f"Health check failed: {e}")

# ==================== DATABASE VIEWER TAB ====================
with db_tab:
    st.subheader("Database Viewer")
    try:
        schema_data = api_client.get_schema()

        st.write("### Tables in Database:")
        for table, columns in schema_data.get("tables", {}).items():
            with st.expander(f"{table}"):
                st.write("Columns:", ", ".join(columns))

                preview_query = f"SELECT * FROM {table} LIMIT {MAX_PREVIEW_ROWS}"
                try:
                    preview_json = api_client.query(preview_query)
                    results = (
                            preview_json.get("results") or
                            preview_json.get("rows") or
                            preview_json.get("data")
                    )
                    if results:
                        st.write(f"Preview (first {MAX_PREVIEW_ROWS} rows):")
                        st.dataframe(results)
                    else:
                        st.warning("Preview returned no results or unexpected format.")
                except APIError as e:
                    st.warning(f"Could not fetch preview: {e}")
                    logger.error(f"Preview error for {table}: {e}")
    except APIError as e:
        st.error(f"Failed to load database schema: {e}")
        logger.error(f"Database viewer error: {e}")

# ==================== CHAT TAB ====================
with chat_tab:
    st.title("Chat with your Assistant")

    # Controls
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🗑️ Clear Chat", use_container_width=True):
            clear_chat()
            st.rerun()

    # Display previous chat messages
    for m in st.session_state.messages:
        role = m.get("role", "assistant")
        with st.chat_message(role):
            st.markdown(m.get("content", ""))

    # Chat input (appears at bottom)
    user_input = st.chat_input("Ask your question...", key="db_chat_input")

    if user_input:
        # Show user's message immediately
        with st.chat_message("user"):
            st.markdown(user_input)
        add_message("user", user_input)

        with st.spinner("Processing..."):
            try:
                data = api_client.chat(st.session_state.user_id, user_input)

                final_answer = data.get("final_answer", "(no answer)")
                sql_query = data.get("sql_query")
                db_results = data.get("db_results")
                is_db = data.get("is_db_question", False)

                # If it's a DB question with SQL, show SQL and answer separately
                if is_db and sql_query:
                    # SQL message (code block)
                    sql_content = f"**SQL:**\n```sql\n{sql_query}\n```"
                    with st.chat_message("assistant"):
                        st.markdown(sql_content)
                    add_message("assistant", sql_content)

                    # Natural-language answer message
                    with st.chat_message("assistant"):
                        st.markdown(final_answer)
                    add_message("assistant", final_answer)
                else:
                    # Normal assistant answer (no SQL)
                    with st.chat_message("assistant"):
                        st.markdown(final_answer)
                    add_message("assistant", final_answer)

                # Add to history
                add_history(user_input, final_answer, {"sql": sql_query, "results": db_results})

                # Save to database (optional)
                try:
                    save_conversation(st.session_state.user_id, user_input, sql_query or "", final_answer)
                except Exception as e:
                    logger.warning(f"Failed to save conversation: {e}")

                st.rerun()

            except APIError as e:
                err = f"Error: {e}"
                with st.chat_message("assistant"):
                    st.error(err)
                add_message("assistant", err)
                add_history(user_input, err, {})
                logger.error(f"Chat error: {e}")