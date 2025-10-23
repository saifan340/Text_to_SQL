from openai import OpenAI
from utils import get_schema_text_from_db
from config import OPENAI_API_KEY, MODEL_NAME
import logging

# Set up logging
logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Default parameters
DEFAULT_SQL_TEMPERATURE = 0.3
DEFAULT_ANSWER_TEMPERATURE = 0.0
DEFAULT_CHAT_TEMPERATURE = 0.7


def _validate_openai_response(response) -> str:
    """
    Validate OpenAI response and extract content.
    
    Args:
        response: OpenAI API response object
        
    Returns:
        str: Extracted and cleaned content
        
    Raises:
        Exception: If response is invalid or empty
    """
    if not response or not response.choices:
        raise Exception("No response choices received from OpenAI")
    
    choice = response.choices[0]
    if not choice.message or not choice.message.content:
        raise Exception("No message content in OpenAI response")
    
    return choice.message.content.strip()

def call_openai_for_sql(user_question: str, schema: str | None = None, temperature: float = DEFAULT_SQL_TEMPERATURE) -> str:
    """
    Generate an SQL query based on a user question + database schema.
    Always expects a schema, but fetches one if not provided.
    
    Args:
        user_question (str): Natural language question about the database
        schema (str, optional): Database schema. If None, fetches from database
        temperature (float): OpenAI temperature parameter (0.0-2.0)
    
    Returns:
        str: Generated SQL query
        
    Raises:
        Exception: If OpenAI API call fails or no response is generated
    """
    try:
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
            temperature=temperature
        )

        sql_query = _validate_openai_response(response)

        # Remove any code fences
        if sql_query.startswith("```"):
            sql_query = "\n".join(line for line in sql_query.splitlines() if not line.startswith("```"))
        
        return sql_query

    except Exception as e:
        logger.error(f"Error generating SQL query: {str(e)}")
        raise Exception(f"Failed to generate SQL query: {str(e)}")


def call_openai_for_answer(
    user_question: str,
    sql_query: str,
    db_results: str | list[dict] | None = None,
    context: str = "",
    model: str = MODEL_NAME,
    temperature: float = DEFAULT_ANSWER_TEMPERATURE
) -> str:
    """
    Generate a natural language answer to a user question using the executed SQL and DB results.
    
    Args:
        user_question (str): The original user question
        sql_query (str): The SQL query that was executed
        db_results (str | list[dict] | None): Results from database execution
        context (str): Conversation history context
        model (str): OpenAI model to use
        temperature (float): OpenAI temperature parameter (0.0-2.0)
    
    Returns:
        str: Natural language answer to the user's question
    """
    try:
        if isinstance(db_results, list):
            db_results = "\n".join(str(row) for row in db_results)
        elif db_results is None:
            db_results = "No results returned"

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert SQL assistant. "
                    "Given the user's question, past conversation, "
                    "and the results from the database, respond in clear, concise, and natural language. "
                    "If the results are empty or show an error, explain what that means in context."
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

        return _validate_openai_response(response)

    except Exception as e:
        logger.error(f"Error generating answer: {str(e)}")
        return f"Error generating answer: {str(e)}"

def call_openai_for_not_db_answer(prompt: str, model: str = MODEL_NAME, temperature: float = DEFAULT_CHAT_TEMPERATURE) -> str:
    """
    Generates a text-based response from the AI for non-database questions.
    Always returns a string.
    
    Args:
        prompt (str): The user's question or prompt
        model (str): OpenAI model to use
        temperature (float): OpenAI temperature parameter (0.0-2.0)
    
    Returns:
        str: AI-generated response to the user's question
    """
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert AI assistant. "
                        "You can answer all general (non-database) questions clearly, concisely, "
                        "and in a readable, natural style. "
                        "Be helpful and informative while staying accurate."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            temperature=temperature
        )
        
        message = _validate_openai_response(response)
        return message if message else "Sorry, I couldn't generate a response."
        
    except Exception as e:
        logger.error(f"Error generating non-database answer: {str(e)}")
        return f"Sorry, I encountered an error while generating a response: {str(e)}"
