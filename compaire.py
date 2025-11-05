import re
from functools import lru_cache

def parse_schema_tokens(schema_text: str):
    """
    From schema text like:
      Table: employees
      Columns: id, name, salary
    Return a set of tokens {employees, id, name, salary}
    """
    if not schema_text:
        return set()

    tokens = set()
    # find "Table: <name>" and "Columns: a, b, c"
    for match in re.finditer(r"Table:\s*([^\n\r]+)\nColumns:\s*([^\n\r]+)", schema_text, flags=re.IGNORECASE):
        table = match.group(1).strip().lower()
        cols = [c.strip().lower() for c in match.group(2).split(",") if c.strip()]
        tokens.add(table)
        tokens.update(cols)

    # as a fallback also gather any bare word-like tokens
    extra = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", schema_text.lower())
    tokens.update(extra)
    return tokens


@lru_cache(maxsize=1)
def get_cached_schema_tokens(schema_text: str):
    # cache one parsed schema to avoid re-parsing each request
    return parse_schema_tokens(schema_text)


def is_db_question(message: str, schema_text: str) -> bool:
    """
    Heuristic + schema-aware classifier for DB questions.
    Returns True when the message likely needs SQL.
    """
    msg = (message or "").lower().strip()
    if not msg:
        return False

    # quick exact-phrase checks (strong signals)
    strong_phrases = [
        "select ", "select*", "select *", "from ", "where ", "group by", "order by",
        " join ", " count", " sum", " avg", " distinct ", "limit ", "top ",
        "sql query", "sql", "query the", "run sql", "execute sql",
    ]
    if any(p in msg for p in strong_phrases):
        return True

    # expanded natural language signals
    nl_signals = [
        "how many", "how much", "total", "calculate total", "calculate", "sum of",
        "employees", "salary", "salaries", "department", "departments",
        "rows", "records", "percentage", "%", "per", "by", "filter", "aggregate",
        "show me", "list all", "list the", "give me a list", "display",
    ]
    if any(p in msg for p in nl_signals):
        return True

    # numeric / currency patterns (strong signal for data queries)
    money_and_numbers = [
        r"\$\s?\d{1,3}(?:[,\d]{0,})",     # $50,000 or $50000
        r"\d{1,3}(?:[,]\d{3})+\b",        # 50,000
        r"\bunder\s+\$?\d+",              # under 50000
        r"\bbelow\s+\$?\d+",
        r"\bover\s+\$?\d+",
        r"\bgreater than\s+\$?\d+",
        r"\bless than\s+\$?\d+",
    ]
    for pat in money_and_numbers:
        if re.search(pat, msg):
            return True

    # schema-aware check: if message mentions a table or column token
    schema_tokens = get_cached_schema_tokens(schema_text)
    if schema_tokens:
        # tokenise message words and look for intersection
        msg_tokens = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", msg))
        if msg_tokens & schema_tokens:
            return True

    # fallback weak patterns (phrases that often imply DB intent)
    fallback = [
        "rows where", "records where", "employees who", "employees earning",
        "how many employees", "count employees", "find employees", "find records",
    ]
    if any(p in msg for p in fallback):
        return True

    return False
