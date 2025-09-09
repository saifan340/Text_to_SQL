from openai_service import call_openai_for_sql, call_openai_for_text
from db import run_sql
from utils import *


schema_text = get_schema_text_from_db()

user_prompt = input("write your prompt? ")

sql_query = call_openai_for_sql(user_prompt, schema_text)

results = run_sql(sql_query)


if results:

    result_list = [row[0] for row in results]
    ai_prompt = f"Convert the following SQL query result into a text for a user:\n{result_list}"

    result_text = call_openai_for_text(ai_prompt)
else:
    result_text = "No results found."

print("Query Results as Text:\n", result_text)



