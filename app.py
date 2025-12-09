import os
import sqlite3
import logging
from flask import Flask, request, jsonify
from utils import get_all_tables_and_columns, get_schema_text_from_db, DB_PATH
from openai_service import call_openai_for_sql, call_openai_for_answer, call_openai_for_not_db_answer, call_openai_for_classification
from db import run_sql, init_db, save_conversation, get_conversation_history
from functools import wraps
from flask_cors import CORS

init_db()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
#DB_PATH = "conversation.db"

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

# --- SQL helpers: paste at top of file ---
import re

_SQL_DETECT_RE = re.compile(r'^\s*(?:--.*\n\s*)*(SELECT|WITH|INSERT|UPDATE|DELETE|PRAGMA|CREATE|DROP)\b', re.IGNORECASE)
_ALLOWED_EXPLICIT = {"SELECT", "WITH"}
_FORBIDDEN_RE = re.compile(r'\b(ATTACH|DETACH|ALTER|VACUUM|REINDEX|PRAGMA\s+user_version)\b', re.IGNORECASE)
_MULTI_STATEMENT_RE = re.compile(r';')

def is_explicit_sql(text: str) -> bool:
    return bool(_SQL_DETECT_RE.match(text))

def top_level_statement(text: str) -> str:
    m = _SQL_DETECT_RE.match(text)
    return m.group(1).upper() if m else ""

def is_safe_explicit_sql(text: str, allowed_top_level=None):
    stmt = top_level_statement(text)
    allowed = allowed_top_level or _ALLOWED_EXPLICIT
    if stmt not in allowed:
        return False, f"Statement '{stmt}' not allowed. Allowed: {sorted(allowed)}"
    if len(_MULTI_STATEMENT_RE.findall(text)) > 1:
        return False, "Multiple SQL statements detected."
    if _FORBIDDEN_RE.search(text):
        return False, "Forbidden SQL detected."
    return True, ""

@app.route("/")
def home():
    return jsonify({
        "message": "Welcome to the Text-to-SQL API!",
        "endpoints": {
            "/health": "GET - Health check",
            "/schema": "GET - Get database schema",
            "/employees": "GET - Get all employees (example)",
            "/query": "POST - Execute custom SQL query",
            "/ask": "POST - Ask natural language question"
        }
    })

@app.route('/schema', methods=['GET'])
@handle_exceptions
def get_schema():
    """Get database schema information"""
    tables = get_all_tables_and_columns()
    return jsonify({
        "tables": tables,
        "table_count": len(tables)
    }), 200
@app.route("/preview", methods=["GET", "POST"])
def preview():
    if request.method == "GET":
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
            logging.exception("schema preview error")
            return jsonify({"error": str(e)}), 500
        finally:
            conn.close()
    try:
        data = request.get_json(force=True)
        sql = data.get("sql")
        if not sql:
            return jsonify({"error": "sql required"}), 400
        rows = run_sql(sql)
        return jsonify({"rows": rows}), 200
    except Exception as e:
        logging.exception("preview POST error")
        return jsonify({"error": str(e)}), 500


@app.route('/queryy', methods=['POST'])
@handle_exceptions
def queryy():
    """Execute a natural language query and return SQL + results"""
    data = request.json
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    prompt = data.get("prompt")
    if not prompt:
        return jsonify({"error": "Missing 'prompt' field"}), 400
    schema = get_schema_text_from_db()
    logger.info(f"Generating SQL for prompt: {prompt}")
    trimmed = prompt.strip()
    if trimmed.upper().startswith(
            ("SELECT", "WITH", "INSERT", "UPDATE", "DELETE","PRAGMA", "CREATE", "DROP")):
        logger.info(f"Generating SQL for query: {trimmed}")
        rows = run_sql(trimmed if trimmed.endswith(";") else trimmed + ";")
        return  jsonify({
            "prompt": prompt,
            "sql": trimmed,
            "results": rows,
            "result_count": len(rows)
        }), 200


    generated_sql= call_openai_for_sql(prompt,schema)

    if not generated_sql:
        return jsonify({"error": "Failed to generate SQL query"}), 400
    try:
        logger.info(f"Executing SQL: {generated_sql}")
        rows = run_sql(generated_sql)

        return jsonify({
            "prompt": prompt,
            "sql": generated_sql,
            "results": rows,
            "result_count": len(rows)
        }), 200

    except Exception as e:
        logger.error(f"SQL execution failed: {str(e)}")
        return jsonify({
            "prompt": prompt,
            "sql": generated_sql,
            "error": f"SQL execution failed: {str(e)}"
        }), 400

@app.route('/query', methods=['POST'])
@handle_exceptions
def query():
    """Execute a natural language query and return SQL + results + explanation."""
    data = request.json
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    prompt = data.get("prompt")
    if not prompt:
        return jsonify({"error": "Missing 'prompt' field"}), 400

    user_id = data.get("user_id")
    history_text = data.get("history", "")

    schema = get_schema_text_from_db()
    trimmed = prompt.strip()

    # If user provided raw SQL, run it directly
    if trimmed.upper().startswith(
        ("SELECT", "WITH", "INSERT", "UPDATE", "DELETE", "PRAGMA", "CREATE", "DROP")
    ):
        sql_to_run = trimmed if trimmed.endswith(";") else trimmed + ";"
        db_results = run_sql(sql_to_run)

        final_answer = call_openai_for_answer(
            user_question=prompt,
            sql_query=sql_to_run,
            db_results=db_results,
            context=history_text,
        )

        return jsonify({
            "user_id": user_id,
            "user_question": prompt,
            "sql_query": sql_to_run,
            "results": db_results,
            "result_count": len(db_results) if isinstance(db_results, list) else 0,
            "final_answer": final_answer,
            "metadata": {"success": True},
            "context_used": history_text
        }), 200

    # Otherwise: natural language -> SQL -> execute -> explain
    try:
        generated_sql = call_openai_for_sql(prompt, schema=schema)
    except Exception as e:
        logger.exception("SQL generation failed")
        return jsonify({"error": f"SQL generation error: {e}"}), 500

    if not generated_sql:
        return jsonify({"error": "Failed to generate SQL query"}), 400

    sql_to_run = generated_sql.strip()
    if not sql_to_run.endswith(";"):
        sql_to_run += ";"

    try:
        db_results = run_sql(sql_to_run)
    except Exception as e:
        logger.exception("SQL execution failed")
        return jsonify({
            "user_id": user_id,
            "user_question": prompt,
            "sql_query": sql_to_run,
            "results": None,
            "error": f"SQL execution error: {e}",
            "metadata": {"success": False}
        }), 500

    # Generate human-readable explanation using the function you shared
    final_answer = call_openai_for_answer(
        user_question=prompt,
        sql_query=sql_to_run,
        db_results=db_results,
        context=history_text,
    )

    return jsonify({
        "user_id": user_id,
        "user_question": prompt,
        "sql_query": sql_to_run,
        "results": db_results,
        "result_count": len(db_results) if isinstance(db_results, list) else 0,
        "final_answer": final_answer,
        "metadata": {"success": True},
        "context_used": history_text
    }), 200

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
        sql_query = call_openai_for_sql(user_question, schema)
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
        final_answer = call_openai_for_answer(
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
        save_conversation(user_id, user_question,sql_query, final_answer)
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
def chat():
    data = request.get_json(force=True)
    schema_text = get_schema_text_from_db()
    logger.info(f"Got chat request: {data}")

    try:
        user_id = data.get("user_id", "default_user")
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"error": "Empty message"}), 400

        # --- Explicit SQL path ---
        if is_explicit_sql(message):
            logger.info(f"User {user_id} sent explicit SQL: {message}")
            ok, reason = is_safe_explicit_sql(message)
            if not ok:
                logger.warning(f"Rejected explicit SQL from user {user_id}: {reason}")
                save_conversation(user_id, message, "", f"SQL rejected: {reason}")
                return jsonify({"error": reason}), 400

            try:
                db_results = run_sql(message)
                logger.info(f"User {user_id} executed explicit SQL successfully: {message}")
                final_answer = f"Done: {len(db_results)} rows."
                save_conversation(user_id, message, message, final_answer)
                return jsonify({
                    "final_answer": final_answer,
                    "sql_query": message,
                    "db_results": db_results,
                    "is_db_question": True,
                    "metadata": {"success": True}
                })

            except Exception as e:
                save_conversation(user_id, message, message, f"Execution failed: {e}")
                return jsonify({"error": str(e)}), 500

        # --- Otherwise classify ---
        try:
            is_db = call_openai_for_classification(message, schema_text)
            logger.info(f"User {user_id} sent message for classification: {message}")
        except Exception as e:
            return jsonify({"error": f"Classification failed: {e}"}), 500

        # --- LLM-generated SQL ---
        if is_db:
            logger.info(f"User {user_id} sent message for DB access: {message}")
            try:
                sql_query = call_openai_for_sql(message, schema_text)
                ok, reason = is_safe_explicit_sql(sql_query, allowed_top_level={"SELECT","WITH","INSERT","UPDATE","DELETE"})
                if not ok:
                    save_conversation(user_id, message, sql_query, f"Rejected: {reason}")
                    return jsonify({"error": reason}), 400

                db_results = run_sql(sql_query)
                logger.info(f"User {user_id} executed DB query successfully: {sql_query}")
                final_answer = call_openai_for_answer(
                    user_question=message,
                    sql_query=sql_query,
                    db_results=db_results,
                    context=""
                )

                save_conversation(user_id, message, sql_query, final_answer)
                logger.info(f"User {user_id} generated final answer: {final_answer}")
                return jsonify({
                    "final_answer": final_answer,
                    "sql_query": sql_query,
                    "db_results": db_results,
                    "is_db_question": True,
                    "metadata": {"success": True}
                })

            except Exception as e:
                return jsonify({"error": f"DB processing failed: {e}"}), 500

        # --- Not DB question ---
        final_answer = call_openai_for_not_db_answer(message )

        logger.info(f"User {user_id} sent message for non-DB access: {message}")
        save_conversation(user_id, message, "", final_answer)
        return jsonify({
            "final_answer": final_answer,
            "is_db_question": False,
            "metadata": {"success": True}
        })

    except Exception as e:
        return jsonify({"error": f"Internal error: {e}"}), 500

if __name__ == '__main__':
    logger.info("Starting Text-to-SQL API server...")
    app.run(
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000) or os.environ.get(
            "FLASK_RUN_PORT", "5000"
        ))
    )