#import os
from openai import OpenAI
#from dotenv import load_dotenv
from utils import get_schema_text_from_db
from config import OPENAI_API_KEY, MODEL_NAME


#load_dotenv()

#MODEL_NAME = "gpt-4o-mini"
#client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
client = OpenAI(api_key=OPENAI_API_KEY)

def call_openai_for_sql(user_question: str, schema: str | None = None) -> str:
    """
    Generate an SQL query based on a user question + database schema.
    Always expects a schema, but fetches one if not provided.
    """
    if schema is None:
        schema = get_schema_text_from_db()

    system_message = (
        "You are an expert SQL assistant. "
        "Given a database schema and a natural language request, generate only the SQL query. "
        "Do not include explanations, comments, or extra text. "
        "Use SQLite syntax."
    )

    user_message = f"Database schema:\n{schema}\n\nUser request: {user_question}"

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        temperature=0.3
    )

    sql_query = response.choices[0].message.content.strip()

    # Remove any code fences
    if sql_query.startswith("```"):
        sql_query = "\n".join(line for line in sql_query.splitlines() if not line.startswith("```"))
    return sql_query


def call_openai_for_answer(
    user_question: str,
    sql_query: str,
    db_results: str | list[dict] | None = None,
    context: str = "",
    model: str = MODEL_NAME,
    temperature: float = 0
) -> str:
    """
    Generate a natural language answer to a user question using the executed SQL and DB results.
    """
    if isinstance(db_results, list):
        db_results = "\n".join(str(row) for row in db_results)

    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert SQL assistant. "
                    "Given the user's question, past conversation, "
                    "and the results from the database, respond in clear, concise, and natural language."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User question:\n{user_question}\n\n"
                    f"Conversation history:\n{context}\n\n"
                    f"Executed SQL:\n{sql_query}\n\n"
                    f"Database results:\n{db_results}"
                ),
            }
        ]

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"Error generating answer: {str(e)}"


def call_openai_for_text(prompt: str, model: str = MODEL_NAME, temperature: float = 0) -> str:
    """
    Return AI-generated text based on a prompt.
    """
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are an expert assistant who summarizes SQL results in clear, readable text."
            },
            {"role": "user", "content": prompt}
        ],
        temperature=temperature
    )
    return response.choices[0].message.content.strip()
