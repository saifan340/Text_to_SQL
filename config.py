import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")  # default fallback
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///employer.db")

# Debugging (optional: print only in dev, not prod)
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in environment variables")
