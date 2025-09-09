import sqlite3

DB_NAME = "employer.db"

def run_sql(query, params=None):
    """
    Run an SQL query against the database.
    - query: SQL string
    - params: optional tuple of values for placeholders
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    if params:
        cursor.execute(query, params)
    else:
        cursor.execute(query)

    if query.strip().lower().startswith("select"):
        result = cursor.fetchall()
    else:
        result = None
        conn.commit()

    conn.close()
    return result

