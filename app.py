import os
import re
import sqlite3
import logging
from pathlib import Path
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS

# =========================
# 1) Load .env EARLY
# =========================
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)

# =========================
# 2) Imports that may use env
# =========================
from utils import get_all_tables_and_columns, get_schema_text_from_db, DB_PATH
from openai_service import (
    call_openai_for_sql,
    call_openai_for_answer,
    call_openai_for_not_db_answer,
    call_openai_for_classification,

)
from db import run_sql, init_db, save_conversation, get_conversation_history

# =========================
# 3) App + Logging
# =========================
init_db()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# =========================
# 4) Error wrapper
# =========================
def handle_exceptions(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.exception(f"Error in {f.__name__}: {e}")
            return jsonify({"error": "Internal server error", "details": str(e)}), 500
    return wrapper


# =========================
# 5) SQL safety helpers
# =========================
_SQL_DETECT_RE = re.compile(
    r'^\s*(?:--.*\n\s*)*(SELECT|WITH|INSERT|UPDATE|DELETE|PRAGMA|CREATE|DROP)\b',
    re.IGNORECASE
)
_ALLOWED_EXPLICIT_DEFAULT = {"SELECT", "WITH"}  # explicit user SQL allowed top-level
_FORBIDDEN_RE = re.compile(r'\b(ATTACH|DETACH|ALTER|VACUUM|REINDEX|PRAGMA\s+user_version)\b', re.IGNORECASE)
_MULTI_STATEMENT_RE = re.compile(r';')

def is_explicit_sql(text: str) -> bool:
    return bool(_SQL_DETECT_RE.match(text or ""))

def top_level_statement(text: str) -> str:
    m = _SQL_DETECT_RE.match(text or "")
    return m.group(1).upper() if m else ""

def is_safe_explicit_sql(text: str, allowed_top_level=None):
    stmt = top_level_statement(text)
    allowed = allowed_top_level or _ALLOWED_EXPLICIT_DEFAULT
    if stmt not in allowed:
        return False, f"Statement '{stmt}' not allowed. Allowed: {sorted(allowed)}"
    # allow 0 or 1 semicolon at end, but not multiple statements
    semis = _MULTI_STATEMENT_RE.findall(text or "")
    if len(semis) > 1:
        return False, "Multiple SQL statements detected."
    if _FORBIDDEN_RE.search(text or ""):
        return False, "Forbidden SQL detected."
    return True, ""


# =========================
# 6) Basic routes
# =========================
@app.route("/health", methods=["GET"])
def api_health():
    return jsonify({"status": "healthy", "service": "text-to-sql-api"}), 200

@app.route("/")
def home():
    return jsonify({
        "message": "Welcome to the Text-to-SQL API!",
        "endpoints": {
            "/health": "GET - Health check",
            "/schema": "GET - Get database schema",
            "/preview": "GET - Show schema preview | POST - run sql and return rows",
            "/query": "POST - Natural language OR SQL execution",
            "/ask": "POST - Ask question with memory",
            "/chat": "POST - Chat endpoint (classify DB vs non-DB)"
        }
    }), 200

@app.errorhandler(404)
def not_found(_error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(405)
def method_not_allowed(_error):
    return jsonify({"error": "Method not allowed"}), 405


# =========================
# 7) Schema endpoint
# =========================
@app.route('/schema', methods=['GET'])
@handle_exceptions
def get_schema():
    tables = get_all_tables_and_columns()
    return jsonify({"tables": tables, "table_count": len(tables)}), 200


# =========================
# 8) Preview endpoint
# =========================
@app.route("/preview", methods=["GET", "POST"])
def preview():
    if request.method == "GET":
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [r[0] for r in cur.fetchall()]
            schema = {}
            for t in tables:
                cur.execute(f"PRAGMA table_info({t});")
                cols = [row[1] for row in cur.fetchall()]
                schema[t] = cols
            return jsonify({"schema": schema}), 200
        except Exception as e:
            logger.exception("schema preview error")
            return jsonify({"error": str(e)}), 500
        finally:
            if conn:
                conn.close()

    # POST
    try:
        data = request.get_json(force=True) or {}
        sql = data.get("sql")
        if not sql:
            return jsonify({"error": "sql required"}), 400

        ok, reason = is_safe_explicit_sql(sql, allowed_top_level={"SELECT", "WITH", "INSERT", "UPDATE", "DELETE"})
        if not ok:
            return jsonify({"error": reason}), 400

        rows = run_sql(sql)
        return jsonify({"rows": rows}), 200
    except Exception as e:
        logger.exception("preview POST error")
        return jsonify({"error": str(e)}), 500


# =========================
# 9) /query endpoint
# =========================
@app.route('/query', methods=['POST'])
@handle_exceptions
def query():
    data = request.get_json(force=True) or {}
    prompt = (data.get("prompt") or "").strip()

    if not prompt:
        return jsonify({"error": "Missing 'prompt' field"}), 400

    schema = get_schema_text_from_db()
    logger.info(f"Generating/Running SQL for prompt: {prompt}")

    # If user sent SQL directly
    if is_explicit_sql(prompt):
        ok, reason = is_safe_explicit_sql(prompt, allowed_top_level={"SELECT", "WITH", "INSERT", "UPDATE", "DELETE"})
        if not ok:
            return jsonify({"error": reason}), 400

        rows = run_sql(prompt)
        return jsonify({
            "prompt": prompt,
            "sql": prompt,
            "results": rows,
            "result_count": len(rows)
        }), 200

    # Otherwise, generate SQL using OpenAI
    generated_sql = call_openai_for_sql(prompt, schema)
    if not generated_sql:
        return jsonify({"error": "Failed to generate SQL query"}), 400

    ok, reason = is_safe_explicit_sql(generated_sql, allowed_top_level={"SELECT", "WITH", "INSERT", "UPDATE", "DELETE"})
    if not ok:
        return jsonify({"error": f"Generated SQL rejected: {reason}", "sql": generated_sql}), 400

    rows = run_sql(generated_sql)
    return jsonify({
        "prompt": prompt,
        "sql": generated_sql,
        "results": rows,
        "result_count": len(rows)
    }), 200


# =========================
# 10) /ask endpoint (memory)
# =========================
@app.route("/ask", methods=["POST"])
@handle_exceptions
def ask_question():
    data = request.get_json(force=True) or {}
    user_question = (data.get("question") or "").strip()
    user_id = data.get("user_id", "default_user")

    if not user_question:
        return jsonify({"error": "Missing 'question' field"}), 400

    schema = get_schema_text_from_db()

    history = get_conversation_history(user_id, limit=5)
    history_text = " ".join(
        [f"[{i+1}] User: {q.strip()}   AI: {a.strip()}" for i, (q, a) in enumerate(history)]
    ) or "No previous context."

    sql_query = call_openai_for_sql(user_question, schema)
    if not sql_query:
        return jsonify({"error": "Failed to generate SQL query"}), 400

    ok, reason = is_safe_explicit_sql(sql_query, allowed_top_level={"SELECT", "WITH", "INSERT", "UPDATE", "DELETE"})
    if not ok:
        save_conversation(user_id, user_question, sql_query, f"Rejected: {reason}")
        return jsonify({"error": reason, "sql_query": sql_query}), 400

    db_results = run_sql(sql_query)

    final_answer = call_openai_for_answer(
        user_question=user_question,
        sql_query=sql_query,
        db_results=db_results,
        context=history_text
    ) or f"Query executed successfully and returned {len(db_results)} results."

    save_conversation(user_id, user_question, sql_query, final_answer)

    return jsonify({
        "user_id": user_id,
        "user_question": user_question,
        "sql_query": sql_query,
        "final_answer": final_answer,
        "db_results": db_results,
        "metadata": {"result_count": len(db_results), "success": True},
        "context_used": history_text
    }), 200


# =========================
# 11) /chat endpoint
# =========================
@app.route("/chat", methods=["POST"])
@handle_exceptions
def chat():
    data = request.get_json(force=True) or {}
    user_id = data.get("user_id", "default_user")
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400

    schema_text = get_schema_text_from_db()

    # Explicit SQL path
    if is_explicit_sql(message):
        ok, reason = is_safe_explicit_sql(message, allowed_top_level={"SELECT", "WITH", "INSERT", "UPDATE", "DELETE"})
        if not ok:
            save_conversation(user_id, message, "", f"SQL rejected: {reason}")
            return jsonify({"error": reason}), 400

        db_results = run_sql(message)
        final_answer = f"{db_results}"
        save_conversation(user_id, message, message, final_answer)
        return jsonify({
            "final_answer": final_answer,
            "sql_query": message,
            "db_results": db_results,
            "is_db_question": True,
            "metadata": {"success": True}
        }), 200

    # Otherwise classify
    is_db = call_openai_for_classification(message, schema_text)

    if is_db:
        sql_query = call_openai_for_sql(message, schema_text)
        ok, reason = is_safe_explicit_sql(sql_query, allowed_top_level={"SELECT", "WITH", "INSERT", "UPDATE", "DELETE"})
        if not ok:
            save_conversation(user_id, message, sql_query, f"Rejected: {reason}")
            return jsonify({"error": reason, "sql_query": sql_query}), 400

        db_results = run_sql(sql_query)
        final_answer = call_openai_for_answer(
            user_question=message,
            sql_query=sql_query,
            db_results=db_results,
            context=""
        )

        save_conversation(user_id, message, sql_query, final_answer)
        return jsonify({
            "final_answer": final_answer,
            "sql_query": sql_query,
            "db_results": db_results,
            "is_db_question": True,
            "metadata": {"success": True}
        }), 200

    # Not DB question
    final_answer = call_openai_for_not_db_answer(message)
    save_conversation(user_id, message, "", final_answer)
    return jsonify({
        "final_answer": final_answer,
        "is_db_question": False,
        "metadata": {"success": True}
    }), 200


# =========================
# 12) Run
# =========================
if __name__ == '__main__':
    logger.info("Starting Text-to-SQL API server...")
    app.run(
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000) or os.environ.get("FLASK_RUN_PORT", "5000"))
    )
