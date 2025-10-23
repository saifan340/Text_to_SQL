import sqlite3

DB_NAME = "conversation.db"


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

def init_db():
    """Ensure the conversations table exists"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            question TEXT,
            sql_query TEXT,
            answer TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
def save_conversation(user_id, question, sql_query, answer):
    """Save a user interaction to DB"""
    run_sql(
        "INSERT INTO conversations (user_id, question, sql_query, answer) VALUES (?, ?, ?, ?)",
        (user_id, question, sql_query, answer)
    )


def get_conversation_history(user_id, limit=5):
    """Fetch the last N interactions for a user"""
    rows = run_sql(
        "SELECT question, answer FROM conversations WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
        (user_id, limit)
    )
    # return oldest → newest
    return rows[::-1] if rows else []

def save_chat_message(user_id, role, content, metadata=None):
    """Save a chat message (user or assistant) to the chat history"""
    run_sql(
        "INSERT INTO conversations (user_id, question, sql_query, answer) VALUES (?, ?, ?, ?)",
        (user_id, content, "", "")  # Using existing table structure
    )

def get_chat_history(user_id, limit=20):
    """Get chat history for a user with proper message structure"""
    rows = run_sql(
        "SELECT question, answer, sql_query, timestamp FROM conversations WHERE user_id = ? ORDER BY timestamp ASC LIMIT ?",
        (user_id, limit)
    )
    
    messages = []
    for row in rows:
        question, answer, sql_query, timestamp = row
        if question:
            messages.append({
                "role": "user",
                "content": question,
                "timestamp": timestamp
            })
        if answer:
            messages.append({
                "role": "assistant", 
                "content": answer,
                "metadata": {"sql": sql_query} if sql_query else {},
                "timestamp": timestamp
            })
    
    return messages

def clear_chat_history(user_id):
    """Clear chat history for a user"""
    run_sql(
        "DELETE FROM conversations WHERE user_id = ?",
        (user_id,)
    )