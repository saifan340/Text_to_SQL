import sqlite3
import os

DB_PATH = "conversation.db"


def get_all_tables_and_columns(db_path=None):
    """
    Reads all tables and their columns from the SQLite database.
    Returns a dict: { "table": ["column1", "column2", ...], ... }
    
    Args:
        db_path (str, optional): Path to the database file. Defaults to DB_PATH.
    
    Returns:
        dict: Dictionary mapping table names to their column lists
        
    Raises:
        sqlite3.Error: If there's an error accessing the database
    """
    if db_path is None:
        db_path = DB_PATH
    
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
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
    except sqlite3.Error as e:
        if 'conn' in locals():
            conn.close()
        raise sqlite3.Error(f"Database error: {e}")

def get_schema_text_from_db(db_path=None):
    """
    Reads the complete table and column structure in text
    form so that OpenAI can use it in SQL generation.
    
    Args:
        db_path (str, optional): Path to the database file. Defaults to DB_PATH.
    
    Returns:
        str: Formatted schema text for OpenAI prompts
        
    Raises:
        sqlite3.Error: If there's an error accessing the database
    """
    try:
        tables = get_all_tables_and_columns(db_path)
        schema_text = ""

        for table, columns in tables.items():
            schema_text += f"Table: {table}\nColumns: {', '.join(columns)}\n\n"

        return schema_text.strip()
    except Exception as e:
        raise sqlite3.Error(f"Error generating schema text: {e}")


def get_table_info(table_name, db_path=None):
    """
    Get detailed information about a specific table including column types.
    
    Args:
        table_name (str): Name of the table to inspect
        db_path (str, optional): Path to the database file. Defaults to DB_PATH.
    
    Returns:
        list: List of tuples with column information (name, type, not_null, default_value, pk)
    """
    if db_path is None:
        db_path = DB_PATH
    
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns_info = cursor.fetchall()
        conn.close()
        return columns_info
    except sqlite3.Error as e:
        if 'conn' in locals():
            conn.close()
        raise sqlite3.Error(f"Database error: {e}")


def validate_table_exists(table_name, db_path=None):
    """
    Check if a table exists in the database.
    
    Args:
        table_name (str): Name of the table to check
        db_path (str, optional): Path to the database file. Defaults to DB_PATH.
    
    Returns:
        bool: True if table exists, False otherwise
    """
    try:
        tables = get_all_tables_and_columns(db_path)
        return table_name in tables
    except Exception:
        return False
