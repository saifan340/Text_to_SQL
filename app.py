import os
from flask import Flask, request, jsonify
from utils import get_all_tables_and_columns, get_schema_text_from_db
from openai_service import call_openai_for_sql, call_openai_for_answer, call_openai_for_not_db_answer, call_openai_for_classification
from db import run_sql, init_db, save_conversation, get_conversation_history
import logging
from functools import wraps
from flask_cors import CORS

init_db()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    """Execute a natural language query and return SQL + results"""
    data = request.json
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    prompt = data.get("prompt")
    if not prompt:
        return jsonify({"error": "Missing 'prompt' field"}), 400

    schema = get_schema_text_from_db()
    logger.info(f"Generating SQL for prompt: {prompt}")
    generated_sql = call_openai_for_sql(prompt, schema)

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
def chat():
    schema_text = get_schema_text_from_db()
    try:
        data = request.get_json(force=True)
        user_id = data.get("user_id", "default_user")
        message = data.get("message", "").strip()

        if not message:
            return jsonify({"error": "Message cannot be empty"}), 400

        # Determine if it's a database question
        is_db = call_openai_for_classification(message, schema_text)

        if is_db:
            schema = get_schema_text_from_db()
            sql_query = call_openai_for_sql(message, schema)

            try:
                db_results = run_sql(sql_query)
            except Exception as e:
                db_results = f"(Error executing SQL: {e})"

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
                "is_db_question": True
            })

        else:
            final_answer = call_openai_for_not_db_answer(
                prompt=message,
                user_id=user_id
            )
            save_conversation(user_id, message, "", final_answer)

            return jsonify({
                "final_answer": final_answer,
                "is_db_question": False
            })

    except Exception as e:
        # Log the error
        print(f"Error in /chat route: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    logger.info("Starting Text-to-SQL API server...")
    app.run(
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000) or os.environ.get(
            "FLASK_RUN_PORT", "5000"
        ))
    )