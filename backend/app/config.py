import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# 載入專案根目錄的 .env 檔案（本機開發用；在 Vercel 上則直接讀取平台環境變數）
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT_DIR / ".env", override=False)


def _require(name: str) -> str:
    """讀取必要的環境變數；缺少時直接報錯，不使用任何寫死的預設值。"""
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(
            f"缺少環境變數 {name}。本機請在專案根目錄的 .env 設定；"
            f"Vercel 請到 Project Settings → Environment Variables 設定。"
        )
    return value


def _require_jwt(name: str) -> str:
    """Supabase 金鑰是 JWT 格式（三段、以兩個句點分隔），用來及早發現複製貼上被截斷的情況。"""
    value = _require(name)
    if value.count(".") != 2 or len(value) < 100:
        raise RuntimeError(
            f"環境變數 {name} 格式不正確（看起來被截斷了）。"
            f"請重新從 Supabase Dashboard → Settings → API 完整複製整串金鑰。"
        )
    return value


class Settings(BaseSettings):
    # Supabase
    SUPABASE_URL: str = _require("SUPABASE_URL")
    SUPABASE_ANON_KEY: str = _require_jwt("SUPABASE_ANON_KEY")
    SUPABASE_SERVICE_ROLE_KEY: str = _require_jwt("SUPABASE_SERVICE_ROLE_KEY")

    # Google AI Studio / Gemini (OpenAI 兼容端點)
    GEMINI_API_KEY: str = _require("GEMINI_API_KEY")
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
