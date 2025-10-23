# Text-to-SQL API

A Flask service that turns natural language questions into SQL using OpenAI, executes the SQL against a SQLite database, and returns both the raw rows and a concise, human-readable answer. Includes both a REST API and Streamlit web interface. Great for no/low-code data querying and prototyping.

## How it works
- Reads your database schema (tables/columns) for context.
- Uses an OpenAI chat model to generate a SQLite SQL query from your question.
- Executes the SQL and returns rows.
- Optionally asks the model to summarize results in plain English.
- Stores conversation history to improve follow‑ups (/ask endpoint) in a `conversations` table.

## Project structure
- app.py — Flask app and HTTP endpoints
- db.py — Lightweight SQLite helpers + conversation storage (uses conversation.db)
- utils.py — Schema introspection helpers (uses conversation.db)
- openai_service.py — Calls to OpenAI chat completions API
- create_db.py — Helper script to create conversation.db from the CSV
- Employers_data.csv — Sample data to seed the DB (employees and details tables)
- streamlit_app.py — Main Streamlit web interface with multiple tabs
- streamlit2_app.py — Simple Streamlit interface for basic testing
- config.py — Environment variable loading and defaults
- conversation.db — SQLite database file
- requirements.txt — Python dependencies (development)
- requirements-prod.txt — Python dependencies (production with exact versions)
- requirements-dev.txt — Development dependencies with testing tools

## Requirements
- Python 3.10+
- An OpenAI API key

Install dependencies:

**For development (recommended):**
```bash
pip install -r requirements.txt
```

**For production (exact versions):**
```bash
pip install -r requirements-prod.txt
```

**For development with testing tools:**
```bash
pip install -r requirements-dev.txt
```

Or install manually:
```bash
pip install -U flask python-dotenv openai pandas streamlit requests
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
This project uses a single SQLite database file (`conversation.db`) for both schema and queries.

1) Seed sample data:

```bash
python create_db.py
```

This reads `Employers_data.csv` and creates two tables in `conversation.db`:
- `employees` table with basic employee information
- `details` table with additional employee details (experience, education, salary)

The database is automatically created if it doesn't exist.

## Run the API
```
python app.py
```

The server listens on 0.0.0.0 and defaults to PORT 5000. You can override with PORT env var.

Health check:
```bash
curl -s http://localhost:5000/health | jq
```

Root page (HTML):
```bash
curl -s http://localhost:5000/
```

## Run the Streamlit Web Interface

The project includes two Streamlit applications:

### Main Streamlit App (Recommended)
```bash
streamlit run streamlit_app.py
```

This provides a comprehensive web interface with multiple tabs:
- **Home**: Welcome page and overview
- **Chat**: Interactive chat interface with conversation history
- **Ask**: Simple question-answer interface
- **Schema**: View database schema and table structure
- **Database Viewer**: Browse table data with previews
- **Health**: Check API health status

### Simple Streamlit App
```bash
streamlit run streamlit2_app.py
```

A minimal interface for basic testing with a single input field.

**Note**: Make sure the Flask API is running before using the Streamlit apps, as they connect to the backend API.

### Streamlit App Features

The main Streamlit app (`streamlit_app.py`) provides:

- **Multi-tab interface** for different functionalities
- **Real-time chat** with conversation history
- **Schema exploration** with interactive table browsing
- **Database preview** showing sample data from tables
- **Health monitoring** for the backend API
- **User session management** with persistent chat history

The simple Streamlit app (`streamlit2_app.py`) provides:
- **Basic question input** interface
- **Direct API integration** for quick testing
- **Minimal setup** for simple use cases

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

## Quick Start

1. **Set up the database:**
   ```bash
   python create_db.py
   ```

2. **Start the Flask API:**
   ```bash
   python app.py
   ```

3. **Run the Streamlit interface:**
   ```bash
   streamlit run streamlit_app.py
   ```

4. **Test with a sample question:**
   Open your browser to the Streamlit app and ask: "How many employees are in the Sales department?"

## Troubleshooting
- **Missing OPENAI_API_KEY**: Set it in .env file or your shell environment
- **No such table: employees**: Run `python create_db.py` to create the database and tables
- **OpenAI errors**: Ensure your API key is correct and the account has access to the selected model
- **Streamlit connection errors**: Make sure the Flask API is running on the correct port (default: 5000)
- **CORS/Network errors**: Add Flask-CORS or a reverse proxy as needed for browser/app integration

## Security notes
- Do not expose this service publicly without authentication and query safety controls. Although the LLM is guided to use SQLite syntax, you should still validate/whitelist SQL or run with restricted permissions.
- Avoid returning sensitive data. Treat the DB as production‑grade only after adding access control and auditing.

## License
No license specified. Add one if you plan to distribute or open‑source.