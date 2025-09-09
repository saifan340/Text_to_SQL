import os
from openai import OpenAI
from dotenv import load_dotenv
from utils import get_all_tables_and_columns, get_schema_text_from_db

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def call_openai_for_sql(user_question: str, schema: str = None) -> str:
    """
    Generate an SQL query based on user question + database schema.
    Always expects a schema, but will fetch one if not provided.
    """
    if schema is None:
        schema = get_schema_text_from_db()  # safer than get_all_tables_and_columns()

    system_message = (
        "You are an expert SQL assistant. "
        "Given a database schema and a natural language request, "
        "generate only the SQL query. "
        "Do not include explanations, comments, or extra text. "
        "Use SQLite syntax."
    )

    user_message = f"Database schema:\n{schema}\n\nUser request: {user_question}"

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message}
        ],
        temperature=0
    )

    sql_query = response.choices[0].message.content.strip()

    # Clean up code fences if model returns ```sql ... ```
    if sql_query.startswith("```"):
        sql_query = sql_query.strip("```").replace("sql", "", 1).strip()

    return sql_query


def call_openai_for_answer(user_question: str, sql_query: str, db_results: list) -> str:
    """
    Convert raw DB results into a short, clear natural language answer.
    """
    prompt = f"""
    User question: {user_question}
    SQL executed: {sql_query}
    DB results: {db_results}

    Please provide a short, clear final answer for the user.
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content.strip()
def call_openai_for_text(prompt):
    """Return AI-generated text based on a prompt."""
    from openai_service import client
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an expert assistant who summarizes SQL results in clear, readable text."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content
