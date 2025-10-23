import os
from flask import Flask, request, jsonify
from utils import get_all_tables_and_columns, get_schema_text_from_db
from openai_service import call_openai_for_sql, call_openai_for_answer
from db import run_sql, init_db, save_conversation, get_conversation_history, get_chat_history, clear_chat_history
import logging
from functools import wraps

init_db()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

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
            "/ask": "POST - Ask natural language question",
            "/chat": "POST - Chat with conversation history",
            "/chat/history": "GET - Get chat history for user",
            "/chat/clear": "POST - Clear chat history for user"
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
@handle_exceptions
def chat():
    """
    Chat endpoint with conversation history:
    - Load chat history for context
    - Process user message (DB or general question)
    - Generate appropriate response
    - Save conversation to history
    """
    data = request.json
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    user_message = data.get("message")
    user_id = data.get("user_id", "default_user")
    chat_id = data.get("chat_id")  # Optional chat session ID

    if not user_message:
        return jsonify({"error": "Missing 'message' field"}), 400

    logger.info(f"User {user_id} sent chat message: {user_message}")

    # Get chat history for context
    try:
        chat_history = get_chat_history(user_id, limit=10)
        logger.info(f"Retrieved {len(chat_history)} messages from chat history")
    except Exception as e:
        logger.error(f"Failed to get chat history: {str(e)}")
        chat_history = []

    # Determine if this is a database question
    is_db_question = _is_db_question(user_message)
    
    try:
        if is_db_question:
            # Handle database question
            schema = get_schema_text_from_db()
            sql_query = call_openai_for_sql(user_message, schema)
            
            if not sql_query:
                response_message = "I couldn't generate a SQL query for your question. Please try rephrasing it."
                sql_query = ""
                db_results = []
            else:
                try:
                    db_results = run_sql(sql_query)
                    logger.info(f"SQL executed successfully, {len(db_results)} rows returned")
                    
                    # Generate natural language answer
                    final_answer = call_openai_for_answer(
                        user_question=user_message,
                        sql_query=sql_query,
                        db_results=db_results,
                        context=""
                    )
                    response_message = final_answer or f"Query executed successfully and returned {len(db_results)} results."
                    
                except Exception as e:
                    logger.error(f"SQL execution failed: {str(e)}")
                    response_message = f"SQL execution failed: {str(e)}"
                    db_results = []
        else:
            # Handle general question (non-database)
            try:
                from openai_service import call_openai_for_not_db_answer
                from config import MODEL_NAME
                response_message = call_openai_for_not_db_answer(
                    prompt=user_message, 
                    model=MODEL_NAME, 
                    temperature=0.7
                )
                if isinstance(response_message, dict):
                    response_message = response_message.get("final_answer") or response_message.get("answer") or str(response_message)
                sql_query = ""
                db_results = []
            except Exception as e:
                logger.error(f"General question processing failed: {str(e)}")
                response_message = f"I encountered an error processing your question: {str(e)}"
                sql_query = ""
                db_results = []

    except Exception as e:
        logger.error(f"Chat processing failed: {str(e)}")
        response_message = f"Sorry, I encountered an error: {str(e)}"
        sql_query = ""
        db_results = []

    # Save conversation to history
    try:
        save_conversation(user_id, user_message, sql_query, response_message)
        logger.info("Conversation saved to history")
    except Exception as e:
        logger.error(f"Failed to save conversation: {str(e)}")

    # Prepare response
    response = {
        "user_id": user_id,
        "chat_id": chat_id,
        "user_message": user_message,
        "assistant_message": response_message,
        "is_db_question": is_db_question,
        "metadata": {
            "sql_query": sql_query,
            "result_count": len(db_results) if db_results else 0,
            "timestamp": None  # Could add timestamp if needed
        },
        "chat_history_count": len(chat_history)
    }

    return jsonify(response), 200


@app.route("/chat/history", methods=["GET"])
@handle_exceptions
def get_chat_history_endpoint():
    """Get chat history for a user"""
    user_id = request.args.get("user_id", "default_user")
    limit = int(request.args.get("limit", 20))
    
    try:
        chat_history = get_chat_history(user_id, limit)
        return jsonify({
            "user_id": user_id,
            "messages": chat_history,
            "count": len(chat_history)
        }), 200
    except Exception as e:
        logger.error(f"Failed to get chat history: {str(e)}")
        return jsonify({"error": f"Failed to get chat history: {str(e)}"}), 500


@app.route("/chat/clear", methods=["POST"])
@handle_exceptions
def clear_chat():
    """Clear chat history for a user"""
    data = request.json or {}
    user_id = data.get("user_id", "default_user")
    
    try:
        clear_chat_history(user_id)
        return jsonify({
            "message": f"Chat history cleared for user {user_id}",
            "user_id": user_id
        }), 200
    except Exception as e:
        logger.error(f"Failed to clear chat history: {str(e)}")
        return jsonify({"error": f"Failed to clear chat history: {str(e)}"}), 500


def _is_db_question(prompt: str) -> bool:
    """Determine if a prompt is asking about the database"""
    if not prompt:
        return False
    
    p = prompt.lower()
    db_keywords = [
        "select", "where", "group by", "order by", "join", "count", "sum",
        "average", "how many", "show", "list", "find", "table", "sql", "query",
        "database", "db", "employees", "salary", "department", "hire date"
    ]
    return any(keyword in p for keyword in db_keywords)


if __name__ == '__main__':
    logger.info("Starting Text-to-SQL API server...")
    app.run(
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000))
    )


