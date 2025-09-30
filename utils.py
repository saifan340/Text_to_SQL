import sqlite3

DB_PATH = "employer.db"


def get_all_tables_and_columns():
    """
    Reads all tables and their columns from the SQLite database.
    Returns a dict: { "table": ["column1", "column2", ...], ... }
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = cursor.fetchall()

    schema_info = {}

    for table in tables:
        table_name = table[0]
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = [col[1] for col in cursor.fetchall()]
        schema_info[table_name] = columns

    conn.close()
    return schema_info

def get_schema_text_from_db():
    """
    Reads the complete table and column structure in text
    form so that OpenAI can use it in SQL generation.
    """
    tables = get_all_tables_and_columns()
    schema_text = ""

    for table, columns in tables.items():
        schema_text += f"Table: {table}\nColumns: {', '.join(columns)}\n\n"

    return schema_text.strip()
