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


@app.route('/query', methods=['POST'])
@handle_exceptions
def query():
    """Execute a natural language query and return SQL + results"""
    data = request.json
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    prompt = data.get("prompt")
    if not prompt:
        return jsonify({"error": "Missing 'prompt' field"}), 400
    schema = get_schema_text_from_db()
    logger.info(f"Generating SQL for prompt: {prompt}")
    trimmed = prompt.strip().upper()
    if trimmed.startwith_any(
            ["SELECT", "WITH", "INSERT", "UPDATE", "DELETE","PRAGMA", "CREATE", "DROP"]):
        return run_sql(trimmed)
    else:

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
@handle_exceptions
def chat():
    """
    POST /chat
    Request JSON:
      { "user_id": "...", "message": "..." }
    Response JSON (examples):
      { "final_answer": "...", "is_db_question": True, "sql_query": "...", "db_results": [...], "metadata": {...} }
    """

    # --- Basic validation & schema retrieval ---
    schema_text = get_schema_text_from_db()
    if not schema_text or not isinstance(schema_text, str) or not schema_text.strip():
        logger.error("Failed to retrieve DB schema")
        return jsonify({"error": "Failed to retrieve database schema"}), 500

    data = request.get_json(force=True) or {}
    user_id = (data.get("user_id") or "default_user").strip()
    message = (data.get("message") or "").strip()

    if not user_id:
        return jsonify({"error": "User ID cannot be empty"}), 400
    if not message:
        return jsonify({"error": "Message cannot be empty"}), 400

    logger.info(f"User {user_id} message received: {message}")

    # --- Heuristic: If user directly sent SQL, execute it (safe in dev, be careful in prod) ---
    sql_prefixes = [
        "SELECT", "WITH", "INSERT", "UPDATE", "DELETE","PRAGMA", "CREATE",
        "DROP"
    ]
    # Use an uppercased copy for prefix check but do NOT mutate the original SQL
    msg_upper = message.lstrip().upper()
    looks_like_raw_sql = any(msg_upper.startswith(p) for p in sql_prefixes)

    if looks_like_raw_sql:
        try:
            db_results = run_sql(message)  # pass original message, not uppercased
            print (db_results)
            # Ensure db_results is JSON-serializable
            return jsonify({
                "final_answer": f"Executed raw SQL. Returned {len(db_results) if hasattr(db_results, '__len__') else 'unknown'} rows.",
                "sql_query": message,
                "db_results": db_results,
                "is_db_question": True,
                "metadata": {"result_count": len(db_results) if hasattr(db_results, '__len__') else None, "success": True}
            }), 200
        except Exception as e:
            logger.exception("Failed executing raw SQL")
            return jsonify({"error": f"Failed to execute SQL: {str(e)}"}), 500

    # --- Otherwise: classify the message (LLM) whether it's DB-related ---
    try:
        is_db_question = call_openai_for_classification( message, schema_text)
    except Exception as e:
        logger.exception("Classification failed")
        return jsonify({"error": f"Failed to classify the message: {str(e)}"}), 500

    # --- If DB-question: generate SQL, execute, create final answer ---
    if is_db_question:
        logger.info("Classified as DB-related")
        try:
            # Generate SQL from LLM (pass schema_text so the model knows the DB)
            sql_query = call_openai_for_sql(message, schema_text)
            print (sql_query)
            if not sql_query or not isinstance(sql_query, str) or not sql_query.strip():
                raise ValueError("Generated SQL query is empty")

            db_results = run_sql(sql_query)

            final_answer = call_openai_for_answer(
                user_question=message,
                sql_query=sql_query,
                db_results=db_results,
                context=""
            ) or f"Query executed successfully and returned {len(db_results) if hasattr(db_results, '__len__') else 'some'} rows."

            save_conversation(user_id, message, sql_query, final_answer)

            return jsonify({
                "final_answer": final_answer,
                "sql_query": sql_query,
                "db_results": db_results,
                "is_db_question": True,
                "metadata": {"result_count": len(db_results) if hasattr(db_results, '__len__') else None, "success": True}
            }), 200

        except Exception as e:
            logger.exception("Failed processing DB question")
            return jsonify({"error": f"Database question processing failed: {str(e)}"}), 500

    # --- Non-DB question path ---
    logger.info("Classified as non-database-related")
    try:
        final_answer = call_openai_for_not_db_answer(prompt=message, user_id=user_id) or "I'm sorry, I couldn't process your request."
        save_conversation(user_id, message, "", final_answer)
        return jsonify({
            "final_answer": final_answer,
            "is_db_question": False,
            "metadata": {"success": True}
        }), 200
    except Exception as e:
        logger.exception("Failed processing non-db question")
        return jsonify({"error": f"Non-database question processing failed: {str(e)}"}), 500

if __name__ == '__main__':
    logger.info("Starting Text-to-SQL API server...")
    app.run(
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000) or os.environ.get(
            "FLASK_RUN_PORT", "5000"
        ))
    )