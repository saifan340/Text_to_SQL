from flask import Flask, request, jsonify
from utils import get_all_tables_and_columns, get_schema_text_from_db
from openai_service import call_openai_for_sql, call_openai_for_text
from db import run_sql

app = Flask(__name__)

@app.route("/")
def home():
    return "Welcome to the Text-to-SQL API!"

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

@app.route("/employees", methods=["GET"])
def get_employees():
    rows = run_sql("SELECT * FROM employees LIMIT 50")
    return jsonify(rows)

@app.route("/schema", methods=["GET"])
def get_schema():
    tables = get_all_tables_and_columns()
    return jsonify(tables), 200

@app.route("/query", methods=["POST"])
def query():
    data = request.get_json()
    prompt = data.get("prompt")

    if not prompt:
        return jsonify({"error": "Missing 'prompt'"}), 400

    schema = get_schema_text_from_db()
    generated_sql = call_openai_for_sql(prompt, schema)

    try:
        rows = run_sql(generated_sql)
        return jsonify({"sql": generated_sql, "results": rows}), 200
    except Exception as e:
        return jsonify({"sql": generated_sql, "error": str(e)}), 400

@app.route("/ask", methods=["POST"])
def ask_question():
    data = request.get_json()
    user_question = data.get("question")

    if not user_question:
        return jsonify({"error": "Missing 'question'"}), 400

    # Step 1: Generate SQL
    schema = get_schema_text_from_db()
    sql_query = call_openai_for_sql(user_question, schema)

    # Step 2: Run SQL
    try:
        db_results = run_sql(sql_query)
    except Exception as e:
        return jsonify({"error": str(e), "sql_query": sql_query}), 500

    # Step 3: Transform into final text
    final_answer = call_openai_for_text(user_question)

    return jsonify({
        "user_question": user_question,


        "final_answer": final_answer
    })

if __name__ == "__main__":
    app.run(debug=True)
