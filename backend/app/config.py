import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# 載入專案根目錄的 .env 檔案
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT_DIR / ".env", override=True)

_DEFAULT_SUPABASE_URL = "https://rrjbfgvfawjthrknvnls.supabase.co"
_DEFAULT_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJyamJmZ3ZmYXdqdGhya252bmxzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTIxNDAzNTAsImV4cCI6MjEwNzcxNjM1MH0."
    "-K5wEED6Dos8rJr5be_IL8BoVxs45GvZI32-Mo5Tayc"
)
_DEFAULT_SR_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJyamJmZ3ZmYXdqdGhya252bmxzIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MjE0MDM1MCwiZXhwIjoyMTA3NzE2MzUwfQ."
    "kg9cKfpqKBTqNwzd5KzvsRCG6qt-b2-lydkjqUnTKzw"
)
_DEFAULT_GEMINI_KEY = "AQ." + "Ab8RN6LssMkidZAlEGS4PV56l4Gw99u-1YyPCQqd6DIBAmPCnw"


def _valid_jwt(val: str, fallback: str) -> str:
    v = (val or "").strip()
    if len(v) > 100 and v.count(".") == 2:
        return v
    return fallback


def _valid_gemini_key(val: str, fallback: str) -> str:
    v = (val or "").strip()
    if len(v) >= 35 and "." in v:
        return v
    return fallback


# 先修正環境變數中可能因複製貼上而被截斷（例如只複製到第一個句點 .）的金鑰
os.environ["SUPABASE_URL"] = os.getenv("SUPABASE_URL", "").strip() or _DEFAULT_SUPABASE_URL
os.environ["SUPABASE_ANON_KEY"] = _valid_jwt(os.getenv("SUPABASE_ANON_KEY", ""), _DEFAULT_ANON_KEY)
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = _valid_jwt(
    os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""), _DEFAULT_SR_KEY
)
os.environ["GEMINI_API_KEY"] = _valid_gemini_key(
    os.getenv("GEMINI_API_KEY", ""), _DEFAULT_GEMINI_KEY
)


class Settings(BaseSettings):
    # Supabase
    SUPABASE_URL: str = os.environ["SUPABASE_URL"]
    SUPABASE_ANON_KEY: str = os.environ["SUPABASE_ANON_KEY"]
    SUPABASE_SERVICE_ROLE_KEY: str = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

    # Google AI Studio / Gemini (OpenAI 兼容端點)
    GEMINI_API_KEY: str = os.environ["GEMINI_API_KEY"]
    LLM_BASE_URL: str = (
        os.getenv("LLM_BASE_URL", "").strip()
        or "https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    LLM_MODEL: str = os.getenv("LLM_MODEL", "").strip() or "gemini-3.5-flash"
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "").strip() or "gemini-embedding-001"

    # LangSmith
    LANGSMITH_TRACING: str = os.getenv("LANGSMITH_TRACING", "true")
    LANGSMITH_ENDPOINT: str = os.getenv(
        "LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"
    )
    LANGSMITH_API_KEY: str = os.getenv("LANGSMITH_API_KEY", "")
    LANGSMITH_PROJECT: str = os.getenv("LANGSMITH_PROJECT", "agentic-rag")


settings = Settings()

# 同步設定環境變數給 LangSmith SDK 自動讀取
if settings.LANGSMITH_API_KEY and len(settings.LANGSMITH_API_KEY.strip()) > 20:
    os.environ["LANGSMITH_TRACING"] = settings.LANGSMITH_TRACING
    os.environ["LANGSMITH_ENDPOINT"] = settings.LANGSMITH_ENDPOINT
    os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY
    os.environ["LANGSMITH_PROJECT"] = settings.LANGSMITH_PROJECT


