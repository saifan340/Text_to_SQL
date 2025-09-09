# Text-to-SQL (Flask + SQLite + OpenAI)

## Quickstart
```bash
cd text_to_sql_project
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # add your OpenAI key
python app.py
```

Now try (in another terminal):

```bash
curl -X POST http://127.0.0.1:5000/ask -H "Content-Type: application/json"   -d '{"question": "How many sales were there last year?"}'
```

## Endpoints
- `GET /` – health check
- `GET /schema` – returns schema text
- `GET /employees` – sample data
- `POST /ask` – body: `{ "question": "..." }` -> returns SQL, rows, final answer
- `POST /sql` – body: `{ "sql": "SELECT ..."} ` -> execute a safe query

## Database
- `data/employees.db` with two tables:
  - `employees(Employee_ID, Name, Age, Gender, Department, Job_Title, Experience_Years, Education_Level, Location, Salary, Hire_Date)`
  - `sales(Sale_ID, Employee_ID, Sale_Date, Amount, Product, Region)`
```

# Security notes
- The backend asks the model to generate **only SELECT** statements and rejects non-SELECT queries.
- Consider additional validation / allow-listing in production.
