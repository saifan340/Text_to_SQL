from threading import Semaphore
import time
import random
import re
import logging
from typing import Optional, List, Dict, Any

from openai import OpenAI ,RateLimitError, OpenAIError

from utils import get_schema_text_from_db
from db import get_conversation_history
from config import (
    OPENAI_API_KEY,
    MODEL_NAME,
    MAX_CONCURRENT,
    MAX_RETRIES,
    BASE_DELAY_SECONDS,
)

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Default temperatures
DEFAULT_SQL_TEMPERATURE = 0.2
DEFAULT_ANSWER_TEMPERATURE = 0.0
DEFAULT_CHAT_TEMPERATURE = 0.7

# Recommended max_tokens per function (from our table)
SQL_MAX_TOKENS = 150
ANSWER_MAX_TOKENS = 300
CHAT_MAX_TOKENS = 600
CLASSIFY_MAX_TOKENS = 10

# Ensure semaphore count is valid
try:
    _max_concurrent = max(1, int(MAX_CONCURRENT))
except Exception:
    logger.warning("Invalid MAX_CONCURRENT in config; defaulting to 1")
    _max_concurrent = 1

semaphore = Semaphore(_max_concurrent)


def _jitter(min_jitter: float = 0.0, max_jitter: float = 0.5) -> float:
    return random.uniform(min_jitter, max_jitter)


def create_chat_completion_with_retries(
    model: str,
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: int,
    max_retries: Optional[int] = None,
    base_delay: Optional[float] = None,
) -> Any:
    """
    Call OpenAI chat completions with retries and exponential backoff.
    IMPORTANT: pass `max_tokens` here so the underlying request is limited.
    Returns the raw OpenAI response object on success (not the extracted text).
    Raises on final failure.
    """
    retries = int(max_retries) if max_retries is not None else int(MAX_RETRIES)
    delay = float(base_delay) if base_delay is not None else float(BASE_DELAY_SECONDS)

    for attempt in range(retries):
        with semaphore:
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                return response
            except RateLimitError as e:
                wait = delay * (2 ** attempt) + _jitter(0, delay)
                logger.warning(
                    "RateLimitError (attempt %d/%d): %s. Backing off %.2fs",
                    attempt + 1,
                    retries,
                    str(e),
                    wait,
                )
                time.sleep(wait)
                continue
            except OpenAIError as e:
                # Other recoverable OpenAI errors: retry similarly
                wait = delay * (2 ** attempt) + _jitter(0, delay)
                logger.warning(
                    "OpenAIError (attempt %d/%d): %s. Backing off %.2fs",
                    attempt + 1,
                    retries,
                    str(e),
                    wait,
                )
                time.sleep(wait)
                continue
            except Exception as e:
                logger.exception("Unexpected exception while calling OpenAI: %s", e)
                raise

    # all retries exhausted
    raise Exception("OpenAI request failed after retries")


def _validate_openai_response(response: Any) -> str:
    """
    Extract and validate text from OpenAI response objects.
    Works with common shapes: response.choices[0].message.content or dict-like shapes.
    """
    if not response:
        raise Exception("No response object from OpenAI")

    # Try to access choices in flexible ways
    choices = None
    try:
        choices = getattr(response, "choices", None)
        if choices is None and isinstance(response, dict):
            choices = response.get("choices")
    except Exception:
        choices = None

    if not choices:
        raise Exception("No response choices received from OpenAI")

    # First choice
    choice = choices[0]
    content = None

    # OpenAI Python client often exposes choice.message.content
    try:
        if hasattr(choice, "message") and getattr(choice.message, "content", None) is not None:
            content = choice.message.content
    except Exception:
        content = None

    # dict-shaped fallback
    if content is None and isinstance(choice, dict):
        msg = choice.get("message") or {}
        content = msg.get("content") or choice.get("text")

    # other fallback
    if content is None:
        content = getattr(choice, "text", None)

    if not content:
        raise Exception("No message content in OpenAI response")

    return str(content).strip()


def _strip_code_fences(text: str) -> str:
    """
    Remove markdown triple-backtick code fences and leading/trailing whitespace.
    Handles fences like ```sql, ```python, or plain ```.
    """
    if not text:
        return text
    # Remove starting fence with optional language
    text = re.sub(r"^```[a-zA-Z0-9]*\n", "", text)
    # Remove trailing fence
    text = re.sub(r"\n```$", "", text)
    return text.strip()


def call_openai_for_sql(
    user_question: str,
    schema: Optional[str] = None,
    temperature: float = DEFAULT_SQL_TEMPERATURE,
    max_tokens: int = SQL_MAX_TOKENS,
) -> str:
    """
    Generate an SQL query from a natural language question and a DB schema.
    Returns the SQL string (no fences).
    """
    try:
        if schema is None:
            schema = get_schema_text_from_db()

        system_message = (
            "You are an expert SQL assistant. "
            "Given a database schema and a natural language request, generate ONLY the SQL query. "
            "Use SQLite syntax. Do not include explanations or comments."
        )
        user_message = f"Database schema:\n{schema}\n\nUser request: {user_question}"

        response = create_chat_completion_with_retries(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        sql_query = _validate_openai_response(response)
        sql_query = _strip_code_fences(sql_query)

        return sql_query

    except Exception as e:
        logger.error("Error generating SQL query: %s", e)
        raise Exception(f"Failed to generate SQL query: {e}")


def call_openai_for_answer(
    user_question: str,
    sql_query: str,
    db_results: Optional[List[Dict[str, Any]]] = None,
    context: str = "",
    model: str = MODEL_NAME,
    temperature: float = DEFAULT_ANSWER_TEMPERATURE,
    max_tokens: int = ANSWER_MAX_TOKENS,
) -> str:
    """
    Create a human-readable explanation from the executed SQL and DB results.
    """
    try:
        if isinstance(db_results, list):
            db_results_str = "\n".join(str(row) for row in db_results) if db_results else "No results returned"
        elif db_results is None:
            db_results_str = "No results returned"
        else:
            db_results_str = str(db_results)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert SQL assistant. "
                    "Given the user's question, past conversation, and the results from the database, "
                    "respond in clear, concise, natural language. If results are empty or show an error, explain what that means."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User question:\n{user_question}\n\n"
                    f"Conversation history:\n{context}\n\n"
                    f"Executed SQL:\n{sql_query}\n\n"
                    f"Database results:\n{db_results_str}"
                ),
            }
        ]

        response = create_chat_completion_with_retries(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return _validate_openai_response(response)

    except Exception as e:
        logger.error("Error generating answer: %s", e)
        return f"Error generating answer: {e}"


def call_openai_for_not_db_answer(
    prompt: str,
    model: str = MODEL_NAME,
    temperature: float = DEFAULT_CHAT_TEMPERATURE,
    user_id: str = "default_user",
    history: Optional[List[Dict[str, str]]] = None,
    max_tokens: int = CHAT_MAX_TOKENS,
) -> str:
    """
    Respond to general (non-database) prompts using persisted and in-session history.
    """
    try:
        db_history = get_conversation_history(user_id=user_id, limit=5)

        messages: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are a helpful conversational assistant. "
                    "Use previous context from the same user to maintain continuity. Answer clearly and naturally."
                ),
            }
        ]

        # Add DB persisted history (assumed list of (q,a))
        for q, a in db_history:
            messages.append({"role": "user", "content": q})
            messages.append({"role": "assistant", "content": a})

        # Add in-session history (if provided)
        if history:
            for msg in history[-6:]:
                if "role" in msg and "content" in msg:
                    messages.append(msg)

        # Current prompt
        messages.append({"role": "user", "content": prompt})

        response = create_chat_completion_with_retries(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return _validate_openai_response(response)

    except Exception as e:
        logger.error("Error generating non-database answer: %s", e)
        return f"Sorry, I encountered an error while generating a response: {e}"


def call_openai_for_classification(question: str, schema_text: str, max_tokens: int = CLASSIFY_MAX_TOKENS) -> bool:
    """
    Classify whether a user question requires a SQL query.
    Returns True (needs SQL) or False (does not).
    """
    try:
        prompt = f"""
You are a strict classifier. Given a user QUESTION and the DATABASE SCHEMA (tables and columns),
decide whether the QUESTION requires running a SQL query against the database.

Return ONLY a single token: true or false (lowercase, no punctuation).

SCHEMA:
{schema_text}

QUESTION:
{question}
"""

        response = create_chat_completion_with_retries(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a classifier that outputs only 'true' or 'false'."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=max_tokens,
        )

        text = _validate_openai_response(response).strip().lower()
        if text.startswith("true"):
            return True
        if text.startswith("false"):
            return False

        logger.warning("Unexpected classifier output: %s", text)
        return False

    except Exception as e:
        logger.error("Error in call_openai_for_classification: %s", e)
        return False