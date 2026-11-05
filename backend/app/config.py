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


def _require_supabase_key(name: str) -> str:
    """
    檢查 Supabase 金鑰格式，及早發現複製貼上被截斷的情況。
    支援兩種格式：
    - 新版金鑰：sb_publishable_...（取代 anon）、sb_secret_...（取代 service_role）
    - 舊版金鑰：JWT 格式（三段、以兩個句點分隔、超過 100 字）
    """
    value = _require(name)
    is_new_style = value.startswith(("sb_publishable_", "sb_secret_")) and len(value) > 30
    is_legacy_jwt = value.count(".") == 2 and len(value) > 100
    if not (is_new_style or is_legacy_jwt):
        raise RuntimeError(
            f"環境變數 {name} 格式不正確（看起來被截斷了）。"
            f"請重新從 Supabase Dashboard → Project Settings → API Keys 完整複製整串金鑰。"
        )
    return value


class Settings(BaseSettings):
    # ===== 地區設定（每個地區都不同）=====
    # 地區代號與名稱：顯示在前端標題、AI 提示詞，以及新社帳號的合成 Email 網域（clubs.<代號>.local）
    DISTRICT_CODE: str = os.getenv("DISTRICT_CODE", "").strip() or "3523"
    DISTRICT_NAME: str = os.getenv("DISTRICT_NAME", "").strip() or f"國際扶輪 {os.getenv('DISTRICT_CODE', '').strip() or '3523'} 地區"

    # Supabase
    SUPABASE_URL: str = _require("SUPABASE_URL")
    SUPABASE_ANON_KEY: str = _require_supabase_key("SUPABASE_ANON_KEY")
    SUPABASE_SERVICE_ROLE_KEY: str = _require_supabase_key("SUPABASE_SERVICE_ROLE_KEY")

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

    # 模組 9：地區管理員帳號（首次登入時自動取得 admin 角色）
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "").strip() or "fruit8428@gmail.com"
    # 模組 10：登入頁「忘記密碼？聯絡管理員」顯示的聯絡方式（預設同管理員 Email）
    ADMIN_CONTACT: str = os.getenv("ADMIN_CONTACT", "").strip() or os.getenv("ADMIN_EMAIL", "").strip() or "fruit8428@gmail.com"
    # 模組 10：各社社密碼紀錄的加密金鑰（未設定則不記錄，管理後台看不到密碼）
    CLUB_PASSWORD_SECRET: str = os.getenv("CLUB_PASSWORD_SECRET", "").strip()
    # 模組 10：新社建立時統一使用的預設社密碼（執秘登入後應自行更改）
    CLUB_DEFAULT_PASSWORD: str = os.getenv("CLUB_DEFAULT_PASSWORD", "").strip() or "123456"

    # 報名系統橋接（AI 小幫手回答「我們社報名了什麼、繳費了沒」）。全部選填；沒設定時工具會回「尚未連接報名系統」
    SIGNUP_SUPABASE_URL: str = os.getenv("SIGNUP_SUPABASE_URL", "").strip()
    SIGNUP_SUPABASE_ANON_KEY: str = os.getenv("SIGNUP_SUPABASE_ANON_KEY", "").strip()
    SIGNUP_STORAGE_KEY: str = os.getenv("SIGNUP_STORAGE_KEY", "").strip() or "rotary_3523_spa_data_v3"
    SIGNUP_PAYMENT_KEY: str = os.getenv("SIGNUP_PAYMENT_KEY", "").strip() or "rotary_3523_payment_records_v1"
    SIGNUP_SITE_URL: str = os.getenv("SIGNUP_SITE_URL", "").strip()

    # 聊天 API 速率限制：每社每分鐘最多幾次（0＝不限制）
    CHAT_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("CHAT_RATE_LIMIT_PER_MINUTE", "").strip() or "10")


settings = Settings()

# 同步設定環境變數給 LangSmith SDK 自動讀取
if settings.LANGSMITH_API_KEY and len(settings.LANGSMITH_API_KEY.strip()) > 20:
    os.environ["LANGSMITH_TRACING"] = settings.LANGSMITH_TRACING
    os.environ["LANGSMITH_ENDPOINT"] = settings.LANGSMITH_ENDPOINT
    os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY
    os.environ["LANGSMITH_PROJECT"] = settings.LANGSMITH_PROJECT
