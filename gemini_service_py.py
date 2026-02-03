import json
import logging
from typing import Optional, List, Dict, Any
from google import genai
from google.genai import types
from config import GEMINI_API_KEY,MODEL_NAME_GEMINI
import json

# Configuration - Replace with your actual values or imports
GEMINI_API_KEY = GEMINI_API_KEY
MODEL_NAME = MODEL_NAME_GEMINI

# Initialize the Gemini Client
client = genai.Client(api_key=GEMINI_API_KEY)
logger = logging.getLogger(__name__)


def unified_llm_gemini(user_question: str, schema: str, db_results: Optional[List[Any]] = None) -> Dict[str, Any]:
    """
    A simple, direct call to Gemini to decide if a DB is needed,
    generate SQL, and provide a natural language answer.
    """

    # Format database results for the prompt
    db_results_text = "\n".join(str(row) for row in db_results) if db_results else "EMPTY"

    system_prompt = """
    You are an intelligent Text-to-SQL assistant.

    Your task:
    1. Decide whether the user's question requires querying the database.
    2. If required, generate a valid SQLite SQL query.
    3. When database results are provided, explain them in clear, natural language.
    4. The final answer MUST always be human-readable.
    5. NEVER return raw SQL as the final answer.
    6. Return ONLY valid JSON.

    JSON format:
    {
      "type": "db" or "chat",
      "sql": "string or null",
      "answer": "string"
    }

    Few-shot examples:

    Example 1:
    User question: "How many employees are in the Sales department?"
    Database schema: employees(id, name, department, salary)
    Database results: [(3)]

    Output:
    {
      "type": "db",
      "sql": null,
      "answer": "There are 3 employees working in the Sales department."
    }

    Example 2:
    User question: "List all employees"
    Database schema: employees(id, name, department, salary)
    Database results: [(1, "Alice", "HR", 50000), (2, "Bob", "Sales", 60000)]

    Output:
    {
      "type": "db",
      "sql": null,
      "answer": "The employees are Alice from HR and Bob from Sales."
    }

    Example 3:
    User question: "What is the average salary in Engineering?"
    Database schema: employees(id, name, department, salary)
    Database results: [(72000.0)]

    Output:
    {
      "type": "db",
      "sql": null,
      "answer": "The average salary in the Engineering department is 72,000."
    }

    Example 4:
    User question: "What is SQL?"
    Database results: EMPTY

    Output:
    {
      "type": "chat",
      "sql": null,
      "answer": "SQL is a language used to query and manage relational databases."
    }
    """

    user_prompt = f"""
    DATABASE SCHEMA:
    {schema}

    USER QUESTION:
    {user_question}

    DATABASE RESULTS:
    {db_results_text}

    RETURN JSON FORMAT:
    {{
      "type": "db" or "chat",
      "sql": "string_or_null",
      "answer": "string"
    }}
    """

    try:
        # Standard calling without manual retry loops
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
                max_output_tokens=600,
                response_mime_type="application/json"  # This ensures valid JSON output
            ),
        )

        # Parse and return the JSON directly from the response text
        return json.loads(response.text)

    except Exception as e:
        logger.error(f"Error calling Gemini: {e}")
        return {
            "type": "error",
            "sql": None,
            "answer": f"I encountered an error: {str(e)}"
        }

# --- Quick Test ---
# schema = "Table: products (id, name, price, stock)"
# result = unified_llm_gemini("What is the price of the laptop?", schema)
# print(result)