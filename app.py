import os
from flask import  Flask, request, jsonify
from utils import get_all_tables_and_columns, get_schema_text_from_db
from openai_service import call_openai_for_sql, call_openai_for_answer
from db import run_sql, init_db, save_conversation, get_conversation_history
import logging
from functools import wraps
# Setup logging
# python
#from db import init_db, run_sql

init_db()
print(run_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='conversations'"))
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)



# Error handler decorator
def handle_exceptions(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {f.__name__}: {str(e)}")
            return jsonify({"error": "Internal server error", "details": str(e)}), 500

    return wrapper


"""@app.route("/")
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
    })"""


@app.route("/")
def home():
    html_content = """
    <html>
    <head><title>Text-to-SQL API</title></head>
    <body>
        <h1>Welcome to the Text-to-SQL API!</h1>
        <h2>Available Endpoints:</h2>
        <ul>
            <li><strong>GET /health</strong> - Health check</li>
            <li><strong>GET /schema</strong> - Get database schema</li>
            <li><strong>GET /employees</strong> - Get all employees (example)</li>
            <li><strong>POST /query</strong> - Execute custom SQL query</li>
            <li><strong>POST /ask</strong> - Ask natural language question</li>
        </ul>

    </body>
    </html>
    """
    return html_content


@app.route("/employees")
@handle_exceptions
def get_employees():
    """Example endpoint to get all employees"""
    rows = run_sql("SELECT * FROM employees")
    return jsonify({
        "count": len(rows),
        "data": rows
    }), 200


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "text-to-sql-api"}), 200


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

    # Get schema for context
    schema = get_schema_text_from_db()

    # Generate SQL using OpenAI
    logger.info(f"Generating SQL for prompt: {prompt}")
    generated_sql = call_openai_for_sql(prompt, schema)

    if not generated_sql:
        return jsonify({"error": "Failed to generate SQL query"}), 400

    # Execute the SQL
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
    user_id = data.get("user_id", "default_user")  # fallback user_id

    if not user_question:
        return jsonify({"error": "Missing 'question' field"}), 400

    logger.info(f"User {user_id} asked: {user_question}")

    # Step 1: Retrieve schema
    try:
        schema = get_schema_text_from_db()
        logger.info("Retrieved database schema")
    except Exception as e:
        logger.error(f"Failed to get schema: {str(e)}")
        return jsonify({"error": "Failed to retrieve database schema"}), 500

    # Step 2: Retrieve conversation history
    history = get_conversation_history(user_id, limit=5)
    history_text = "\n\n".join([f"User: {q}\nAI: {a}" for q, a in history]) or "No previous context."

    # Step 3: Generate SQL query
    try:
        sql_query = call_openai_for_sql(user_question, schema)
        if not sql_query:
            return jsonify({"error": "Failed to generate SQL query"}), 400
        logger.info(f"Generated SQL: {sql_query}")
    except Exception as e:
        logger.error(f"SQL generation failed: {str(e)}")
        return jsonify({"error": f"SQL generation failed: {str(e)}"}), 500

    # Step 4: Execute SQL
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

    # Step 5: Generate natural language answer
    try:
        # Include history in context
        final_answer = call_openai_for_answer(
            user_question,
            sql_query,
            db_results,
            context=history_text  # 👈 pass history to LLM
        )
        if not final_answer:
            final_answer = f"Query executed successfully and returned {len(db_results)} results."
        logger.info("Generated final answer")
    except Exception as e:
        logger.error(f"Answer generation failed: {str(e)}")
        final_answer = f"Query executed successfully and returned {len(db_results)} results. (Answer generation failed: {str(e)})"

    # Step 6: Save interaction
    try:
        save_conversation(user_id, user_question, sql_query, final_answer)
    except Exception as e:
        logger.error(f"Failed to save conversation: {str(e)}")

    # Step 7: Return full response
    response = {
        "user_id": user_id,
        "user_question": user_question,
        "sql_query": sql_query,
        "db_results": db_results,
        "final_answer": final_answer,
        "metadata": {
            "result_count": len(db_results),
            "success": True
        },
        "context_used": history_text
    }

    return jsonify(response), 200

@app.route("/ask_form", methods=["GET", "POST"])
def ask_form():
    if request.method == "POST":
        user_id = "demo_user"  # or from session
        question = request.form["question"]

        # call your existing ask logic
        schema_text = get_schema_text_from_db()
        history = get_conversation_history(user_id, limit=5)
        history_context = "\n".join([f"Q: {q} | A: {a}" for q, a in history])

        system_prompt = f"Conversation so far:\n{history_context}\n\nSchema:\n{schema_text}"

        sql_query = call_openai_for_sql(question, system_prompt)
        results = run_sql(sql_query)
        answer = call_openai_for_answer(question, results)

        save_conversation(user_id, question, sql_query, answer)

        return f"<h3>Question:</h3>{question}<br><h3>Answer:</h3>{answer}<br><h3>SQL:</h3>{sql_query}"

    return """
        <form method="post">
            <label>Ask a question:</label><br>
            <input type="text" name="question" style="width:300px">
            <input type="submit" value="Ask">
        </form>
    """


@app.route("/health", methods=["GET"])
def api_health():
    """API version of health endpoint"""
    return jsonify({"status": "healthy", "service": "text-to-sql-api", "version": "api"}), 200


# Error handlers for the app
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({"error": "Method not allowed"}), 405


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500


if __name__ == '__main__':
    logger.info("Starting Text-to-SQL API server...")
    #app.run(debug=True, host='0.0.0.0', port=5000)

    app.run(
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000))
    )

