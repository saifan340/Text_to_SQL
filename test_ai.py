from openai_service import call_openai_for_sql, call_openai_for_text, call_openai_for_answer
from db import run_sql
from utils import get_schema_text_from_db

schema_text = get_schema_text_from_db()

user_prompt = input("Write your prompt: ")

sql_query = call_openai_for_sql(user_prompt, schema_text)
print(f"\nGenerated SQL:\n{sql_query}\n")

results = run_sql(sql_query)

if results:

    result_list = [row if len(row) > 1 else row[0] for row in results]
    result_text = call_openai_for_answer(user_prompt, sql_query, result_list)
else:
    result_text = "No results found."

print("\nQuery Results as Text:\n", result_text)
