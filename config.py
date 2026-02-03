import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
MODEL_NAME_GEMINI = os.getenv("MODEL_NAME_GEMINI", "gemini-2.5-flash")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///conversation.db")
MAX_CONCURRENT =os.getenv("MAX_CONCURRENT", "MAX_CONCURRENT")
MAX_RETRIES = os.getenv("MAX_RETRIES", "MAX_RETRIES")
BASE_DELAY_SECONDS = os.getenv("BASE_DELAY_SECONDS", "BASE_DELAY_SECONDS")
API_URL = os.getenv("API_URL", "http://localhost:5000").rstrip("/")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in environment variables")
