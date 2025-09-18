# Text-to-SQL API

A small Flask service that turns natural‑language questions into SQL using OpenAI, executes the SQL against a SQLite database, and returns both the raw rows and a concise, human‑readable answer. Great for no/low‑code data querying and prototyping.

## How it works
- Reads your database schema (tables/columns) for context.
- Uses an OpenAI chat model to generate a SQLite SQL query from your question.
- Executes the SQL and returns rows.
- Optionally asks the model to summarize results in plain English.
- Stores conversation history to improve follow‑ups (/ask endpoint) in a `conversations` table.

## Project structure
- app.py — Flask app and HTTP endpoints
- db.py — Lightweight SQLite helpers + conversation storage (uses employer.db)
- utils.py — Schema introspection helpers (defaults to database.db)
- openai_service.py — Calls to OpenAI chat completions API
- create_db.py — Helper script to create employer.db from the CSV
- Employers_data.csv — Sample data to seed the DB (employees table)
- test_ai.py — Simple CLI to try text→SQL→answer loop
- config.py — Env var loading and defaults
- employer.db / database.db — SQLite files (see DB notes below)

## Requirements
- Python 3.10+
- An OpenAI API key

Install dependencies (no requirements.txt provided):

```
pip install -U flask python-dotenv openai pandas
```

## Environment variables
Create a .env file in the project root with at least:

```
OPENAI_API_KEY=sk-your-key
```

Optional:
- MODEL_NAME=gpt-4o-mini (default used by code)
- FLASK_DEBUG=true (to enable debug)
- PORT=5000 (server port)

## Data and database setup
This project expects an employees table in a SQLite DB.

1) Seed sample data (employer.db):

```
python create_db.py
```

This reads Employers_data.csv and writes an employees table into employer.db.

2) Important: pick a single database for both schema and queries
- db.py runs queries against employer.db.
- utils.py reads schema from database.db by default.

To keep things consistent, do ONE of the following:
- Easiest: edit utils.py and set `DB_PATH = "employer.db"` so schema and queries use the same file; or
- Copy/align your schema into database.db if you prefer to keep them separate.

If you see errors like "no such table: employees" from /schema or /ask, it usually means the schema/DB files are out of sync.

Note on file names (case sensitivity): the CSV in the repo is named "Employers_data.csv" (capital E) while create_db.py references "employers_data.csv" (lowercase). On case‑sensitive filesystems, rename the file or update the script accordingly.

## Run the API
```
python app.py
```

The server listens on 0.0.0.0 and defaults to PORT 5000. You can override with PORT env var.

Health check:
```
curl -s http://localhost:5000/health | jq
```

Root page (HTML):
```
curl -s http://localhost:5000/
```

## API reference
- GET /health — Service health JSON
- GET /schema — Returns discovered tables/columns
- GET /employees — Example: returns all rows from employees
- POST /query — Generates SQL for your prompt and executes it
- POST /ask — Like /query but also uses recent conversation as context and stores Q/A to DB
- GET/POST /ask_form — Minimal HTML form for manual testing

Examples

Generate and run SQL from a prompt:
```
curl -s -X POST http://localhost:5000/query \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "List the first 5 employees by salary"}' | jq
```

Ask with memory and natural‑language answer:
```
curl -s -X POST http://localhost:5000/ask \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "alice", "question": "How many employees are in Sales?"}' | jq
```

Typical response contains: your question, generated SQL, raw db_results, final_answer, and metadata.

## Try it from the CLI
```
python test_ai.py
```
You will be prompted for a question; the script will show the generated SQL and a summarized answer.

## Troubleshooting
- Missing OPENAI_API_KEY: set it in .env or your shell env.
- No such table: employees: run create_db.py to (re)create employer.db, or align utils.DB_PATH with employer.db.
- OpenAI errors: ensure your key is correct and the account has access to the selected model.
- CORS/Network when calling from a browser/app: add Flask-CORS or a reverse proxy as needed.

## Security notes
- Do not expose this service publicly without authentication and query safety controls. Although the LLM is guided to use SQLite syntax, you should still validate/whitelist SQL or run with restricted permissions.
- Avoid returning sensitive data. Treat the DB as production‑grade only after adding access control and auditing.

## License
No license specified. Add one if you plan to distribute or open‑source.