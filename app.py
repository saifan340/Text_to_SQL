import os
from flask import Flask, request, jsonify
from utils import get_all_tables_and_columns, get_schema_text_from_db
from openai_service import call_openai_for_sql, call_openai_for_answer, call_openai_for_not_db_answer, call_openai_for_classification
from db import run_sql, init_db, save_conversation, get_conversation_history
import logging
from functools import wraps
from flask_cors import CORS
import time
import random
from threading import Semaphore

# --- Configuration (env) ---
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "3"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
BASE_DELAY = float(os.getenv("BASE_DELAY", "1.0"))  # seconds
MAX_BACKOFF = float(os.getenv("MAX_BACKOFF", "20.0"))  # cap backoff
JITTER = float(os.getenv("JITTER", "0.25"))

# Semaphore to limit concurrent LLM calls
_llm_semaphore = Semaphore(MAX_CONCURRENT)

# Initialization
init_db()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app setup
app = Flask(__name__)
CORS(app)


def handle_exceptions(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {f.__name__}: {str(e)}")
            return jsonify({"error": "Internal server error", "details": str(e)}), 500

    return wrapper


# --- Utility: detect if prompt already is SQL ---
SQL_KEYWORDS = ("SELECT", "WITH", "INSERT", "UPDATE", "DELETE", "PRAGMA", "CREATE", "DROP", "ALTER")

def is_sql_prompt(prompt: str) -> bool:
    if not prompt:
        return False
    trimmed = prompt.strip()
    # check start
    upper = trimmed.upper()
    for kw in SQL_KEYWORDS:
        if upper.startswith(kw + " ") or upper == kw:
            return True
    # also treat single-line statements that end with a semicolon as SQL
    if trimmed.endswith(';'):
        return True
    return False


# --- LLM wrapper with concurrency limit + retries for 429 ---
def _looks_like_429(exc: Exception) -> bool:
    # heuristics: check attributes or message for 429 / TooManyRequests
    code = getattr(exc, 'status_code', None) or getattr(exc, 'status', None)
    if code == 429:
        return True
    msg = str(exc).lower()
    if '429' in msg or 'too many requests' in msg or 'rate limit' in msg:
        return True
    return False


def llm_call_with_retries(func, *args, **kwargs):
    """
    Calls an LLM helper function (like call_openai_for_sql) with a Semaphore to limit
    concurrent calls and retries on 429 responses using exponential backoff + jitter.

    func: callable
    """
    last_exception = None
    for attempt in range(MAX_RETRIES):
        # block if semaphore not available
        acquired = _llm_semaphore.acquire(timeout=60)
        if not acquired:
            # semaphore exhausted for too long
            raise Exception("Could not acquire LLM semaphore (timeout)")
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            if _looks_like_429(e):
                # compute backoff with jitter
                backoff = min(BASE_DELAY * (2 ** attempt), MAX_BACKOFF)
                jitter = random.uniform(0, JITTER)
                sleep_time = backoff + jitter
                logger.warning(f"LLM 429 detected; retry #{attempt + 1} after {sleep_time:.2f}s (err={e})")
                time.sleep(sleep_time)
                continue
            else:
                # non-429, re-raise
                _llm_semaphore.release()
                raise
        finally:
            # release only if we still hold it (i.e., not returned)
            if _llm_semaphore._value < MAX_CONCURRENT:
                try:
                    _llm_semaphore.release()
                except Exception:
                    pass
    # if we exhausted retries
    logger.error(f"LLM call failed after {MAX_RETRIES} retries: {last_exception}")
    raise last_exception


# --- Flask endpoints (unchanged behavior but using wrappers / SQL detection) ---
@app.route("/health", methods=["GET"])
def api_health():
    """API version of health endpoint"""
    return jsonify({"status": "healthy", "service": "text-to-sql-api", "version": "api"}), 200


@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({"error": "Method not allowed"}), 405


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500


@app.route("/")
def home():
    return jsonify({
        "message": "Welcome to the Text-to-SQL API!",
        "endpoints": {
            "/health": "GET - Health check",
            "/schema": "GET - Get database schema",
            "/employees": "GET - Get all employees (example)",
            "/query": "POST - Execute custom SQL query",
            "/ask": "POST - Ask natural language question",
            "/chat": "POST - Chat (auto-classify db vs non-db)"
        }
    })


@app.route("/employees")
@handle_exceptions
def get_employees():
    """Example endpoint to get all employees"""
    rows = run_sql("SELECT * FROM employees")
    return jsonify({
        "count": len(rows),
        "data": rows
    }), 200


@app.route('/schema', methods=['GET'])
@handle_exceptions
def get_schema():
    """Get database schema information"""
    tables = get_all_tables_and_columns()
    return jsonify({
        "tables": tables,
        "table_count": len(tables)
    }), 200

@app.route('/query', methods=['POST'])
@handle_exceptions
def query():
    """Execute a natural language query and return SQL + results

    Now accepts aliases: 'prompt' OR 'sql' OR 'sql_query'.
    Provides clearer logging for mismatched payloads.
    """
    data = request.json
    if not data:
        logger.error("Empty JSON body on /query")
        return jsonify({"error": "JSON body required"}), 400

    # accept multiple possible keys for SQL prompt
    prompt = data.get('prompt') or data.get('sql') or data.get('sql_query')
    if not prompt:
        logger.error(f"/query missing 'prompt'. Received keys: {list(data.keys())}")
        return jsonify({"error": "Missing 'prompt' field (accepted: 'prompt', 'sql', 'sql_query')"}), 400

    schema = get_schema_text_from_db()
    logger.info(f"Processing query prompt: {prompt}")

    # 1) If prompt already looks like SQL, skip LLM
    if is_sql_prompt(prompt):
        try:
            logger.info("Prompt detected as SQL — executing directly without LLM")
            rows = run_sql(prompt)
            return jsonify({
                "prompt": prompt,
                "sql": prompt,
                "results": rows,
                "result_count": len(rows),
                "note": "executed directly (no model call)"
            }), 200
        except Exception as e:
            logger.error(f"Direct SQL execution failed: {e}")
            return jsonify({"error": "SQL execution failed", "details": str(e)}), 400

    # otherwise call LLM (wrapped)
    try:
        logger.info(f"Generating SQL for prompt: {prompt}")
        generated_sql = llm_call_with_retries(call_openai_for_sql, prompt, schema)

        if not generated_sql:
            return jsonify({"error": "Failed to generate SQL query"}), 400

        logger.info(f"Executing SQL: {generated_sql}")
        rows = run_sql(generated_sql)

        return jsonify({
            "prompt": prompt,
            "sql": generated_sql,
            "results": rows,
            "result_count": len(rows)
        }), 200

    except Exception as e:
        logger.error(f"SQL generation/execution failed: {str(e)}")
        return jsonify({
            "prompt": prompt,
            "error": f"SQL generation/execution failed: {str(e)}"
        }), 400


# Lightweight admin-friendly preview endpoint (safe)
@app.route('/table_preview', methods=['POST'])
@handle_exceptions
def table_preview():
    """Return a safe preview for a table name provided in {"table": "tablename"}.

    This endpoint runs: SELECT * FROM <table> LIMIT 20
    It validates the table name against discovered schema to avoid injection and errors.
    """
    data = request.json or {}
    table = data.get('table')
    if not table:
        return jsonify({"error": "Missing 'table' field"}), 400

    # validate table exists
    all_tables = get_all_tables_and_columns()
    if table not in all_tables:
        return jsonify({"error": f"Unknown table '{table}'", "available_tables": list(all_tables.keys())}), 400

    # build safe preview SQL
    preview_sql = f"SELECT * FROM {table} LIMIT 20"
    try:
        rows = run_sql(preview_sql)
        return jsonify({"table": table, "rows": rows, "row_count": len(rows)}), 200
    except Exception as e:
        logger.error(f"Preview for table {table} failed: {e}")
        return jsonify({"error": "Preview query failed", "details": str(e)}), 400


@app.route("/ask", methods=["POST"])
@handle_exceptions
def ask_question():
    """
    Ask endpoint with memory:
    - Load past conversations
    - Add them as context
    - Generate SQL + answer
    - Save new interaction
    """
    data = request.json
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    user_question = data.get("question")
    user_id = data.get("user_id", "default_user")

    if not user_question:
        return jsonify({"error": "Missing 'question' field"}), 400

    logger.info(f"User {user_id} asked: {user_question}")

    try:
        schema = get_schema_text_from_db()
        logger.info("Retrieved database schema")
    except Exception as e:
        logger.error(f"Failed to get schema: {str(e)}")
        return jsonify({"error": "Failed to retrieve database schema"}), 500

    history = get_conversation_history(user_id, limit=5)
    history_text = " ".join([
        f"[{i + 1}] User: {q.strip()}   AI: {a.strip()}"
        for i, (q, a) in enumerate(history)
    ]) or "No previous context."

    try:
        # If the user question is already SQL, skip model
        if is_sql_prompt(user_question):
            sql_query = user_question
        else:
            sql_query = llm_call_with_retries(call_openai_for_sql, user_question, schema)

        if not sql_query:
            return jsonify({"error": "Failed to generate SQL query"}), 400
        logger.info(f"Generated SQL: {sql_query}")
    except Exception as e:
        logger.error(f"SQL generation failed: {str(e)}")
        return jsonify({"error": f"SQL generation failed: {str(e)}"}), 500

    try:
        db_results = run_sql(sql_query)
        logger.info(f"SQL executed successfully, {len(db_results)} rows returned")
    except Exception as e:
        logger.error(f"SQL execution failed: {str(e)}")
        return jsonify({
            "error": f"SQL execution failed: {str(e)}",
            "sql_query": sql_query,
            "user_question": user_question
        }), 500
    try:
        final_answer = llm_call_with_retries(
            call_openai_for_answer,
            user_question,
            sql_query,
            db_results,
            context=history_text
        )
        if not final_answer:
            final_answer = f"Query executed successfully and returned {len(db_results)} results."
        logger.info("Generated final answer")
    except Exception as e:
        logger.error(f"Answer generation failed: {str(e)}")
        final_answer = f"Query executed successfully and returned {len(db_results)} results. (Answer generation failed: {str(e)})"

    try:
        save_conversation(user_id, user_question, sql_query, final_answer)
    except Exception as e:
        logger.error(f"Failed to save conversation: {str(e)}")

    response = {
        "user_id": user_id,
        "user_question": user_question,
        "sql_query": sql_query,
        "final_answer": final_answer,
        "metadata": {
            "result_count": len(db_results),
            "success": True
        },
        "context_used": history_text
    }

    return jsonify(response), 200


@app.route("/chat", methods=["POST"])
@handle_exceptions
def chat():
    """
    Chat endpoint that handles both database-related and general questions.
    - Classifies if question needs database query
    - Handles SQL queries and non-database questions
    - Saves conversation history
    """
    data = request.json
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    user_id = data.get("user_id", "default_user")
    message = data.get("message") or data.get("prompt", "").strip()

    if not message:
        return jsonify({"error": "Message or prompt cannot be empty"}), 400

    logger.info(f"User {user_id} asked: {message}")

    try:
        schema_text = get_schema_text_from_db()
    except Exception as e:
        logger.error(f"Failed to get schema: {str(e)}")
        return jsonify({"error": "Failed to retrieve database schema"}), 500

    # Determine if it's a database question
    try:
        is_db = llm_call_with_retries(call_openai_for_classification, message, schema_text)
    except Exception as e:
        logger.error(f"Classification failed: {str(e)}")
        # Default to treating as DB question if classification fails
        is_db = True

    if is_db:
        try:
            schema = get_schema_text_from_db()
            # Skip model if message looks like SQL
            if is_sql_prompt(message):
                sql_query = message
            else:
                sql_query = llm_call_with_retries(call_openai_for_sql, message, schema)

            if not sql_query:
                return jsonify({"error": "Failed to generate SQL query"}), 400

            try:
                db_results = run_sql(sql_query)
            except Exception as e:
                logger.error(f"SQL execution failed: {str(e)}")
                return jsonify({
                    "error": f"SQL execution failed: {str(e)}",
                    "sql_query": sql_query,
                    "is_db_question": True
                }), 400

            # Get conversation history for context
            history = get_conversation_history(user_id, limit=5)
            history_text = " ".join([
                f"[{i + 1}] User: {q.strip()}   AI: {a.strip()}"
                for i, (q, a) in enumerate(history)
            ]) or "No previous context."

            try:
                final_answer = llm_call_with_retries(
                    call_openai_for_answer,
                    user_question=message,
                    sql_query=sql_query,
                    db_results=db_results,
                    context=history_text
                )
            except Exception as e:
                logger.error(f"Answer generation failed: {str(e)}")
                final_answer = f"Query executed successfully and returned {len(db_results)} results. (Answer generation failed: {str(e)})"

            try:
                save_conversation(user_id, message, sql_query, final_answer)
            except Exception as e:
                logger.error(f"Failed to save conversation: {str(e)}")

            return jsonify({
                "final_answer": final_answer,
                "sql_query": sql_query,
                "db_results": db_results,
                "is_db_question": True,
                "metadata": {
                    "result_count": len(db_results) if isinstance(db_results, list) else 0
                }
            }), 200

        except Exception as e:
            logger.error(f"Database question handling failed: {str(e)}")
            return jsonify({"error": f"Failed to process database question: {str(e)}"}), 500

    else:
        try:
            final_answer = llm_call_with_retries(call_openai_for_not_db_answer, prompt=message, user_id=user_id)
            try:
                save_conversation(user_id, message, "", final_answer)
            except Exception as e:
                logger.error(f"Failed to save conversation: {str(e)}")

            return jsonify({
                "final_answer": final_answer,
                "is_db_question": False
            }), 200

        except Exception as e:
            logger.error(f"Non-database question handling failed: {str(e)}")
            return jsonify({"error": f"Failed to process question: {str(e)}"}), 500


if __name__ == '__main__':
    logger.info("Starting Text-to-SQL API server...")
    app.run(
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000) or os.environ.get(
            "FLASK_RUN_PORT", "5000"
        ))
    )
